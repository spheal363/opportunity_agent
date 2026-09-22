"""Agent Run の作成・状態取得。"""

import uuid
from datetime import UTC, datetime

from sqlalchemy import and_, or_
from sqlalchemy.orm import Session

from ai import interstitial, region
from ai import window as search_window
from config import get_settings
from models import DEFAULT_USER_ID, AgentLog, AgentRun, Opportunity, UserProfile
from schemas.agent import (
    AgentLogEntry,
    AgentRunCreated,
    AgentRunHistory,
    AgentRunHistoryEntry,
    AgentRunResult,
    AgentRunState,
    AgentRunStatus,
    AgentRunTrigger,
    AgentStep,
    SearchCandidate,
)
from schemas.opportunity import OpportunitySummary
from services.run_lifecycle import active_runs, expire_abandoned_runs, start_lock


def start_manual_run(db: Session, user_id: str) -> tuple[AgentRunCreated, bool]:
    """実行中ならその run を返す。bool が True のときだけ呼び出し側が実行する。"""
    with start_lock:
        now = datetime.now(UTC)
        settings = get_settings()
        expire_abandoned_runs(db, user_id, now, settings)
        active = active_runs(db, user_id, now, settings)
        if active:
            run = max(active, key=lambda r: (r.created_at, r.run_id))
            return AgentRunCreated(run_id=run.run_id, status=run.status), False
        run_id = create_run(db, user_id)
        return AgentRunCreated(run_id=run_id, status=AgentRunStatus.QUEUED), True


def create_run(
    db: Session,
    user_id: str = DEFAULT_USER_ID,
    *,
    trigger: AgentRunTrigger = AgentRunTrigger.MANUAL,
    reason: str | None = None,
) -> str:
    """run を作る。実行（run_agent）は呼び出し側。

    `reason` は Agent が自分で始めたときの「なぜ始めたか」（services/auto_explore.py）。
    **決まった文面と数値だけを渡すこと。** 画面にそのまま出る。
    """
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    db.add(
        AgentRun(
            run_id=run_id,
            user_id=user_id,
            status=AgentRunStatus.QUEUED,
            trigger=trigger,
            trigger_reason=reason,
            # **マイクロ秒まで持たせる。** server_default（CURRENT_TIMESTAMP）は秒までで、
            # 同じ秒に作った run のどちらが新しいか分からなくなる。自動探索は
            # 「最新の run」「最後の自動 run」で判定するので、前後を取り違えると困る。
            # 保存は他の列と同じく tz なしの UTC。
            created_at=datetime.now(UTC).replace(tzinfo=None),
        )
    )
    if reason:
        # 探索中画面の先頭に「なぜ始めたか」を出す。**AgentStep は増やさない。**
        # 最初のステップ（プロフィール分析）の記録として置く。Agent Loop の
        # 最初の Log はこれより後に書かれる。
        db.add(AgentLog(run_id=run_id, step=AgentStep.ANALYZING_PROFILE, message=reason))
    db.commit()
    return run_id


def latest_row(db: Session, user_id: str) -> AgentRun | None:
    """その人の最新の run（状態は問わない）。無ければ None。"""
    return (
        db.query(AgentRun)
        .filter(AgentRun.user_id == user_id)
        .order_by(AgentRun.created_at.desc(), AgentRun.run_id.desc())
        .first()
    )


def list_runs(
    db: Session, user_id: str, *, limit: int = 20, before: str | None = None
) -> AgentRunHistory | None:
    """本人の履歴を新しい順に返す。無効・他人のカーソルは None。"""
    query = db.query(AgentRun).filter(AgentRun.user_id == user_id)
    if before is not None:
        cursor = db.get(AgentRun, before)
        if cursor is None or cursor.user_id != user_id:
            return None
        query = query.filter(
            or_(
                AgentRun.created_at < cursor.created_at,
                and_(AgentRun.created_at == cursor.created_at, AgentRun.run_id < cursor.run_id),
            )
        )
    rows = query.order_by(AgentRun.created_at.desc(), AgentRun.run_id.desc()).limit(limit + 1).all()
    page = rows[:limit]
    items = [
        AgentRunHistoryEntry.model_validate(row, from_attributes=True).model_copy(
            update={"selected_count": None if row.selected_ids is None else len(row.selected_ids)}
        )
        for row in page
    ]
    return AgentRunHistory(items=items, next_cursor=page[-1].run_id if len(rows) > limit else None)


def get_latest_run(db: Session, user_id: str) -> AgentRunState | None:
    """その人の最新の run。無ければ None。

    Agent が自分で始めた探索（trigger が manual 以外）を画面が見つけるのに使う。
    他人の run は返さない（#69）。
    """
    row = latest_row(db, user_id)
    if row is None:
        return None
    return AgentRunState.model_validate(row, from_attributes=True)


def get_run(db: Session, run_id: str, user_id: str) -> AgentRunState | None:
    """その人の run だけを返す（#69）。他人の run は存在しないのと同じに扱う。"""
    row = db.get(AgentRun, run_id)
    if row is None or row.user_id != user_id:
        return None
    state = AgentRunState.model_validate(row, from_attributes=True)
    # **原文とは別枠。** AI が整理した方向を、原文の置き換えに使わない。
    state.goal_directions = _goal_directions(row)
    return state


def list_logs(db: Session, run_id: str) -> list[AgentLogEntry]:
    """run の Log。**呼ぶ前に `get_run` で所有者を確かめること。**"""
    rows = db.query(AgentLog).filter(AgentLog.run_id == run_id).order_by(AgentLog.id.asc()).all()
    return [AgentLogEntry.model_validate(r, from_attributes=True) for r in rows]


def _profile_changed_since(db: Session, run) -> bool:
    """この run のあとにプロフィールが編集されたか（#47）。

    **編集しただけでは探索は走らない。** 画面が「いまの希望の結果」に
    見えてしまうので、区別できるようにする。
    """
    profile = db.get(UserProfile, run.user_id)
    if profile is None or profile.updated_at is None or run.created_at is None:
        return False
    return profile.updated_at > run.created_at


def _goal_directions(run) -> list[str]:
    """AI が整理した探索方向。**原文の置き換えには使わない。**"""
    ga = run.goal_analysis or {}
    return list(ga.get("wanted_now") or [])


def latest_result(db: Session, user_id: str) -> AgentRunResult | None:
    """**そのユーザーの最新の完了 run**の結果（#47）。

    ホームはここを見る。`GET /api/opportunities` は保存一覧の母集合で、
    **複数 run の候補が混ざる**。実測で、ホームが過去 run の候補まで
    全部並べ、「3つの機会」の横に 59 と出ていた。

    **評価できなかった run でも、古い run のおすすめで埋めない。**
    最新の run の結果をそのまま返す。
    """
    row = (
        db.query(AgentRun)
        .filter(AgentRun.user_id == user_id, AgentRun.status == AgentRunStatus.COMPLETED.value)
        # 同じ秒に 2 件あっても順序が決まるようにする。
        .order_by(AgentRun.created_at.desc(), AgentRun.updated_at.desc())
        .first()
    )
    # **他人の run は見えない。** #86 で足した user_id を必ず通す。
    return get_result(db, row.run_id, user_id) if row is not None else None


def get_result(db: Session, run_id: str, user_id: str) -> AgentRunResult | None:
    """この run の最終選定を順位順で返す。

    **`GET /api/opportunities` とは別経路。** あちらは status で絞った最新の
    一覧（保存一覧の母集合）で、こちらは**その run が選んだものだけ**。

    区別するもの:
      run が無い        -> None（呼び出し側が 404）
      未完了            -> recorded=False, status=running
      結果の記録が無い   -> recorded=False（列を足す前の古い run）
      完了したが 0 件    -> recorded=True, selected=[]
    """
    run = db.get(AgentRun, run_id)
    if run is None or run.user_id != user_id:
        return None

    ids = run.selected_ids
    if ids is None:
        # **失敗したときこそ理由が要る。** 「記録されていません」だけでは、
        # 設定が足りないのか、探しても見つからなかったのかが分からない。
        return AgentRunResult(
            run_id=run_id,
            status=run.status,
            recorded=False,
            error=run.error,
            wishes_source=run.wishes_source,
            region_source=run.region_source,
            goal_directions=_goal_directions(run),
            discovery_route=run.discovery_answers is not None,
        )

    rows = {
        r.opportunity_id: r
        for r in db.query(Opportunity)
        .filter(Opportunity.opportunity_id.in_(ids), Opportunity.user_id == user_id)
        .all()
    }
    win = search_window.SearchWindow.from_dict(run.search_window)
    # 希望した地域。**プロフィールの現在値を使う**（run には保存していない）。
    profile = db.get(UserProfile, run.user_id)
    wanted = profile.location if profile is not None else None
    # **順位を保つ。** DB の返す順ではなく selected_ids の順。
    selected = [_summary(rows[i], win, wanted) for i in ids if i in rows]

    # **推薦しなかったが、読んで抽出できた候補。**
    #
    # 条件は「この run で見つけ」「本文から抽出できている」こと。
    # 検索しただけで読んでいない候補は `Opportunity` の行にならないので、
    # ここには入らない。**未読の保留候補を、確認済みの推薦と同じ扱いにしない。**
    #
    # 一覧を開くだけで外部 API は呼ばない。DB にある分だけを返す。
    chosen = set(ids)
    others = [
        _summary(r, win, wanted)
        for r in db.query(Opportunity)
        .filter(Opportunity.run_id == run_id, Opportunity.user_id == run.user_id)
        .order_by(Opportunity.score.desc())
        .all()
        if r.opportunity_id not in chosen
    ]
    return AgentRunResult(
        run_id=run_id,
        status=run.status,
        wishes_source=run.wishes_source,
        region_source=run.region_source,
        goal_directions=_goal_directions(run),
        discovery_route=run.discovery_answers is not None,
        recommended_count=run.recommended_count or 0,
        profile_changed_since=_profile_changed_since(db, run),
        recorded=True,
        selected=selected,
        others=others,
        search_candidates=_search_candidates(db, run, chosen, win),
        shortfall_reason=run.shortfall_reason,
        search_window=({**win.to_dict(), "days": win.days} if win else None),
        # **失敗の理由を隠さない。** 設定不足なら直せる。
        error=run.error,
    )


def _summary(
    row: Opportunity, win: "search_window.SearchWindow | None", wanted: str | None = None
) -> OpportunitySummary:
    """期間との関係を付けて返す。**期間が分からない run では付けない。**

    この列が付く前の run を、今日の日付で作り直した期間で判定しない。
    """
    out = OpportunitySummary.model_validate(row, from_attributes=True)
    # **地域の照合は期間と独立。** 期間が分からない run でも出す。
    match = region.classify(
        wanted=wanted,
        location=row.location,
        opportunity_format=row.format,
        region=row.region,
        online_participation=row.online_participation,
    )
    out.region_match = match.value
    out.region_note = region.note(match, wanted=wanted, location=row.location)
    if win is None:
        return out
    status = search_window.classify(
        opportunity_type=row.type,
        start_at=row.start_at,
        end_at=row.end_at,
        window=win,
    )
    out.window_status = status.value
    out.window_note = search_window.label(status, win)
    return out


def _search_candidates(
    db: Session, run: AgentRun, chosen: set[str], win: "search_window.SearchWindow | None"
) -> list[SearchCandidate]:
    """検索で見つかった候補を一覧にする。**外部 API は呼ばない。**

    保存済みの検索候補と、抽出できた Opportunity 行を URL で突き合わせる。

    **読んでいない候補に日時や受付状況を付けない。** 検索結果の公開日や
    抜粋中の日付を開催日として流用しない。分からないものは分からないまま返す。

    この列が付く前の run では空を返す。**件数を水増ししない。**
    """
    rows_all = (
        db.query(Opportunity)
        .filter(Opportunity.run_id == run.run_id, Opportunity.user_id == run.user_id)
        .all()
    )
    saved = run.search_candidates or []
    if not saved:
        # **この列が付く前の run。** 検索候補そのものは残っていない。
        # 読んで抽出できた分だけは Opportunity から復元できるので、それを出す。
        # **読まなかった候補は復元できない。** 件数を 20 に水増ししない。
        saved = [{"title": r.title, "url": r.url} for r in rows_all if r.url]

    rows = {r.url: r for r in rows_all if r.url}
    out: list[SearchCandidate] = []
    seen: set[str] = set()
    for item in saved:
        url = (item or {}).get("url")
        if not url or url in seen:
            # **同じ URL を 2 度出さない。**
            continue
        seen.add(url)
        row = rows.get(url)
        # **取得失敗の中間ページは通常の候補として出さない（#47）。**
        # 古い run にはフィルタを通す前の行が残っている。
        if interstitial.looks_like_interstitial(
            title=(row.title if row is not None else item.get("title")),
            content=(row.description if row is not None else None),
        ):
            continue
        if row is None:
            out.append(SearchCandidate(title=(item.get("title") or url)[:200], url=url, read=False))
            continue
        out.append(
            SearchCandidate(
                title=row.title or item.get("title") or url,
                url=url,
                read=True,
                recommended=row.opportunity_id in chosen,
                start_at=row.start_at,
                start_at_is_date_only=row.start_at_is_date_only,
                window_status=(
                    search_window.classify(
                        opportunity_type=row.type,
                        start_at=row.start_at,
                        end_at=row.end_at,
                        window=win,
                    ).value
                    if win
                    else None
                ),
                availability=row.availability,
                verified=bool(row.verified),
            )
        )
    return out
