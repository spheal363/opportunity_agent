"""検索専用モデルの探索経路（#47）。**旧経路は壊さない。切り替えで戻せる。**

    希望の分割（Goal Analysis の出力を使う）
      -> 希望ごとに並列で検索専用モデルへ -> 足りない希望だけ追加で巡回
      -> 行形式の回答をコードで構造化 -> コードで確認できる範囲を判定
      -> 候補として保存し、一覧を返す

**ここでやらないこと**

    検索語の組み立て（モデルが自分で作る）
    本文の取得と抽出（詳細確認へ回す）
    全件の LLM 評価（一覧表示の必須処理にしない）
    TOP3 への絞り込み（候補一覧をそのまま見せる）

**一覧に出る値は未確認。** 引用 URL があることは「公式で確認した」ではない。
これは設計上の限界であり、`verified=False` と `confirmed_fields=[]` で表す。
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from agent.state import AgentState
from ai import cost, discovery, matching
from ai.routing import Step
from models.agent_run import AgentRun
from models.opportunity import Opportunity
from models.user_profile import UserProfile
from schemas.agent import AgentStep
from schemas.opportunity import OpportunityStatus, OpportunityType

# 希望のラベルは**モデルに作らせない**。分割結果をそのまま使う。
MAX_WISHES = 8


def _label(text: str, index: int) -> str:
    """一覧の見出しに使う短い名前。**元の文を捨てない**（wish_source に残す）。"""
    head = (text or "").strip().splitlines()[0] if text else ""
    return (head[:24] or f"希望{index + 1}").strip()


def run(
    db: Session,
    state: AgentState,
    profile: UserProfile,
    win,
    *,
    log: Callable,
    step: Callable,
) -> list[str]:
    wishes_raw = list(state.goal_analysis.wanted_now)[:MAX_WISHES] if state.goal_analysis else []
    if not wishes_raw:
        # **希望が無いのに検索しない。** 推測で埋めると別物を探しに行く。
        log(db, state, AgentStep.SEARCHING, "探したい内容を読み取れませんでした")
        return []

    # 分割した希望 -> 表示ラベル。**原文は profile.wants_now をそのまま持つ。**
    wishes = {_label(w, i): w for i, w in enumerate(wishes_raw)}
    original = profile.wants_now or "\n".join(wishes_raw)
    wanted_region = profile.location or ""
    region_text = (
        f"{wanted_region}。{wanted_region}内で現地参加できるもの。オンラインのみは対象外。"
        if wanted_region
        else "指定なし"
    )

    step(db, state, AgentStep.SEARCHING, "希望ごとにWebを探索しています")
    for text in wishes.values():
        log(db, state, AgentStep.SEARCHING, f"探索する希望: {text}")

    with cost.step(str(Step.DISCOVERY)):
        result = discovery.discover(
            wishes=wishes,
            region=region_text,
            win=win,
            wanted_region_text=wanted_region,
        )

    for line in result.failures:
        # **取得できなかったことを「候補 0 件」と書かない。**
        log(db, state, AgentStep.SEARCHING, f"回答を取得できませんでした — {line}")
    for label, reasons in result.not_found.items():
        for r in dict.fromkeys(reasons):
            log(db, state, AgentStep.SEARCHING, f"{label}: {r}")

    ordered = discovery.order(result.candidates)
    ids = _save(db, state, ordered, original)
    usable = [c for c in ordered if c.excluded is None]
    log(
        db,
        state,
        AgentStep.SEARCHING,
        f"{result.rounds}巡で候補{len(ordered)}件（条件に合うもの{len(usable)}件）を見つけました",
    )
    log(
        db,
        state,
        AgentStep.SEARCHING,
        "一覧の候補は検索結果であって、出典で確認したものではありません",
    )
    run_row = db.get(AgentRun, state.run_id) if state.run_id else None
    if run_row is not None:
        run_row.search_candidates = [
            {"title": c.name, "url": c.source_url, "wish": c.wish} for c in ordered
        ]
        # **回答と引用 URL を保存する。** 一覧は本文を取りに行かないので、
        # あとから追えるのはこれだけ。
        run_row.discovery_answers = result.answers
        # **旧経路は `_verify_and_finalize` で書いていた。** この経路は
        # そこを通らないので、使用量がどこにも残っていなかった（実測）。
        db.commit()
    # --- 評価（検索とは別の工程）---
    #
    # **本文は取りに行かない。** 取得済みの情報だけで、まとめて 1 回評価する。
    # **失敗しても一覧は残す。架空の点を付けない。**
    step(db, state, AgentStep.EVALUATING, "希望との合い方を評価しています")
    rows = [db.get(Opportunity, i) for i in ids]
    rows = [r for r in rows if r is not None and matching.recommendable(r)]
    judged = matching.judge(
        rows,
        wishes=original,
        region=wanted_region,
        window=(f"{win.start:%Y年%m月%d日}〜{win.end:%Y年%m月%d日}" if win else None),
    )
    if judged:
        for r in rows:
            j = judged.get(r.opportunity_id)
            if j is None:
                continue
            r.evaluated = True
            r.score = j.match
            r.reason = j.reason
            # **合致した希望と、判断に必要な未確認事項を分けて残す。**
            r.match_reasons = list(j.matched_wishes)
            r.unknowns = list(j.unknowns)
        db.commit()
        top = matching.order(rows, judged, limit=3)
        log(
            db,
            state,
            AgentStep.EVALUATING,
            f"{len(judged)}件を評価し、{len(top)}件をおすすめにしました",
        )
    else:
        top = []
        # **未評価を「おすすめ」と呼ばない。**
        log(db, state, AgentStep.EVALUATING, "評価できませんでした。候補は一覧のまま残します")

    # 先頭がおすすめ。**同じ候補を 2 つの枠に出さない。**
    top_ids = [r.opportunity_id for r in top]
    state.selected_ids = top_ids + [i for i in ids if i not in top_ids]
    run_row = db.get(AgentRun, state.run_id) if state.run_id else None
    if run_row is not None:
        run_row.selected_ids = list(state.selected_ids)
        run_row.recommended_count = len(top_ids)
        tracker = cost.current()
        if tracker is not None:
            run_row.usage_json = tracker.to_dict()
        db.commit()
    return ids


def _save(db: Session, state: AgentState, cands: list, original: str) -> list[str]:
    ids: list[str] = []
    for c in cands:
        start_at = _at(c.dates[0]) if c.dates else None
        # **別々の開催日を会期の開始・終了として持たない。**
        # 「9/22 と 10/04 の 2 回開催」を 9/22〜10/04 の会期として保存していた。
        # 終了日は、回答が `..` で会期として書いたときだけ入れる。
        is_span = ".." in (c.dates_raw or "")
        end_at = _at(c.dates[-1]) if (is_span and len(c.dates) > 1) else None
        row = Opportunity(
            opportunity_id=f"opp_{uuid.uuid4().hex[:12]}",
            user_id=state.user_id,
            run_id=state.run_id,
            type=OpportunityType.EVENT.value,
            title=c.name,
            description=c.summary,
            url=c.source_url,
            source="検索専用モデル",
            start_at=start_at,
            end_at=end_at,
            # **時刻は書かれていない。** 終日として扱い、架空の時刻を入れない。
            start_at_is_date_only=True if start_at else None,
            end_at_is_date_only=True if end_at else None,
            location=c.venue,
            region=c.region,
            wish=c.wish,
            wish_source=original,
            searched_values={
                "name": c.name,
                "dates": list(c.dates),
                "dates_raw": c.dates_raw,
                "venue": c.venue,
                "region": c.region,
                "source_url": c.source_url,
                "cited": c.cited,
                # **一覧段階でコードだけで分かったこと。** 応答時に
                # `services/agent_service` が期間・地域を算出し直すので、
                # ここでは「条件外と判断した理由」だけを残す。
                "schedule_fit": c.schedule_fit,
                "schedule_note": c.schedule_note,
                "excluded": c.excluded,
            },
            corrections=[],
            confirmed_fields=[],
            participation_span=c.participation_span,  # **根拠が無ければ None**
            evaluated=False,  # **一覧に LLM 評価を必須にしない**
            score=0,
            serendipity_score=0,
            verified=False,
            url_is_source_only=True,
            # **ユーザーへ提示する候補として扱う。** TOP3 の推薦とは違い、
            # 「検索で見つかった候補」として一覧に出す（未確認であることは
            # verified=False / confirmed_fields=[] が表す）。
            status=OpportunityStatus.RECOMMENDED.value,
        )
        db.add(row)
        ids.append(row.opportunity_id)
    db.commit()
    return ids


# 検索の回答は**現地の日付**。UTC の 00:00 として入れると前日に見える。
JST = ZoneInfo("Asia/Tokyo")


def _at(iso: str) -> datetime | None:
    """日付だけの値を、**現地の 0 時**として持つ。時刻は作らない。"""
    try:
        return datetime.combine(date.fromisoformat(iso), time(0, 0), tzinfo=JST)
    except ValueError:
        return None
