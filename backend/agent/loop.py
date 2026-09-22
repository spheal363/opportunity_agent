"""Agent Loop。

    PLAN -> SEARCH -> EVALUATE -> REFLECT -> SEARCH AGAIN -> VERIFY -> SELECT

各ステップは AgentRun / AgentLog に進捗を書き出すので、Frontend は
GET /api/agent/runs/{run_id} をポーリングするだけで Agent の行動を表示できる。

現状は AGENT_STUB_MODE=true の経路だけが動く。
LLM / Web Search を実装する後続タスクで、各 _step_* の中身を差し替える。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import replace
from datetime import UTC, datetime
from urllib.parse import unquote_plus, urlparse

from sqlalchemy.orm import Session

from agent import demo_attack, stub_data
from agent.state import AgentState
from ai import availability, cost, guard
from ai import window as search_window
from ai.concurrency import map_parallel
from ai.evaluation import TOP_N, evaluate_many, recommend, select_top
from ai.extraction import extract_many
from ai.goal_analysis import analyze_goal
from ai.jev.prefilter import rank_for_reading
from ai.llm import LLMError
from ai.schemas import GoalAnalysisOutput, SearchDirection
from ai.schemas.evaluation import EvaluationOutput
from ai.schemas.extraction import GATING_DEADLINES, DeadlineKind, ExtractedOpportunity
from ai.schemas.goal_analysis import GoalAnalysisInput
from ai.search_plan import plan_search
from ai.verification import verify_with_page
from config import FALLBACK_TO_A, get_settings
from config import missing_keys as config_missing_keys
from db.session import SessionLocal
from logging_config import describe_exception, get_logger
from models import AgentLog, AgentRun, Opportunity, UserProfile
from schemas.agent import AgentRunStatus, AgentStep
from schemas.opportunity import OpportunityStatus
from tools import registry
from tools.search.base import PageContent, SearchError, SearchResult

logger = get_logger(__name__)

# 1 つの探索方向あたりに取る検索結果の件数。
# 増やすほど候補は増えるが、1 件ごとに LLM 抽出が走るので時間とコストが伸びる。
# 削減は Search Cost Optimization（P2）の範囲。
MAX_RESULTS_PER_DIRECTION = 5

# 参加の締切だと確認できた区分。これ以外は「閉じる根拠」にしない。
_GATING_KINDS = frozenset({k.value for k in GATING_DEADLINES})

# ユーザーが自分で決めた状態。Agent が再探索で上書きしない。
# status は「ユーザー操作」由来の列（.claude/rules/architecture.md）。
_USER_DECIDED = frozenset(
    {
        OpportunityStatus.INTERESTED,
        OpportunityStatus.REGISTERED,
        OpportunityStatus.ATTENDED,
        OpportunityStatus.DISMISSED,
    }
)

# ステップごとの進捗（Frontend の探索中画面用）
_PROGRESS = {
    AgentStep.ANALYZING_PROFILE: 15,
    AgentStep.PLANNING: 30,
    AgentStep.SEARCHING: 60,
    AgentStep.EVALUATING: 80,
    AgentStep.VERIFYING: 95,
    AgentStep.COMPLETED: 100,
}


def run_agent(run_id: str, user_id: str) -> None:
    """1 回の Agent 実行。BackgroundTask から呼ばれる想定。

    呼び出し元とは別セッションを使う（リクエストの寿命に縛られないため）。
    """
    db = SessionLocal()
    # この run で起きた LLM 呼び出しの消費量を集める。失敗しても記録は残す
    # （失敗した run のコストが 0 として扱われないようにするため）。
    with cost.track(), _closing(db):
        _run(db, run_id, user_id)


@contextmanager
def _closing(db: Session) -> Iterator[None]:
    try:
        yield
    finally:
        db.close()


def _run(db: Session, run_id: str, user_id: str) -> None:
    try:
        state = AgentState(run_id=run_id, user_id=user_id, status=AgentRunStatus.RUNNING)
        settings = get_settings()
        if not settings.agent_stub_mode and (missing := config_missing_keys(settings)):
            # **黙って別構成へ落とさない。** 鍵が無いことと、候補が
            # 見つからないことは別。理由が分かる形で止める。
            _fail(
                db,
                state,
                "探索に必要な設定が足りません: "
                + "、".join(missing)
                + f"。構成 A へ戻すには {FALLBACK_TO_A}",
            )
            return
        profile = db.get(UserProfile, user_id)
        if profile is None:
            _fail(db, state, "プロフィールが登録されていません")
            return

        # **期間はここで確定する（#47）。** 以降どこでも今日を取り直さない。
        # 探索は 2 分ほどかかるので、途中で日付が変わると判定がずれる。
        win = search_window.for_now()
        state.search_window = win.to_dict()
        run = db.get(AgentRun, run_id)
        if run is not None:
            run.search_window = state.search_window
            db.commit()
        _log(
            db,
            state,
            AgentStep.ANALYZING_PROFILE,
            f"探索の対象期間: {win.start:%Y/%m/%d}〜{win.end:%Y/%m/%d}"
            f"（{win.days}日間 / {win.timezone}）",
        )

        _step(db, state, AgentStep.ANALYZING_PROFILE, "プロフィールを分析しています")
        with cost.step("goal_analysis"):
            state.goal_analysis = _analyze_goal(profile)
        _log(db, state, AgentStep.ANALYZING_PROFILE, state.goal_analysis.goal_summary)

        _step(db, state, AgentStep.PLANNING, "何を探すべきか計画しています")
        with cost.step("search_plan"):
            state.search_directions = _plan_search(state, profile)
        for d in state.search_directions:
            _log(db, state, AgentStep.PLANNING, f"探索対象に設定: {d.query}（{d.reason}）")

        _step(db, state, AgentStep.SEARCHING, "Webを探索しています")
        found = _search_and_extract(db, state)
        _log(db, state, AgentStep.SEARCHING, f"{len(found)}件のOpportunityを発見")

        _step(db, state, AgentStep.EVALUATING, "Opportunityを評価しています")
        ranked = _evaluate_and_select(db, state, found)
        _log(db, state, AgentStep.EVALUATING, f"{len(found)}件から{len(ranked)}件を順位付け")

        _step(db, state, AgentStep.VERIFYING, "上位候補の公式情報を確認しています")
        _verify_and_finalize(db, state)
        if state.shortfall_reason:
            _log(db, state, AgentStep.VERIFYING, state.shortfall_reason)
        else:
            _log(db, state, AgentStep.VERIFYING, f"{len(state.selected_ids)}件を推薦します")

        state.status = AgentRunStatus.COMPLETED
        _step(db, state, AgentStep.COMPLETED, "探索が完了しました")
    except Exception as exc:  # Agent 全体を落とさず run を failed にする
        # 例外の文字列はログにも出さない。型と場所だけ残す（describe_exception）。
        logger.error("agent run failed run_id=%s %s", run_id, describe_exception(exc))
        db.rollback()
        _fail(db, AgentState(run_id=run_id, user_id=user_id), _public_error(exc))


def _public_error(exc: Exception) -> str:
    """画面に出す失敗理由（#81）。**例外の文字列は載せない。**

    run の `error` は GET /api/agent/runs/{id} でそのまま返る。例外の文字列には
    SQL とパラメータ（プロフィール本文）や外部 API の応答が入りうるため、
    種類ごとの決まった文言にする。原因を追うための例外の型と場所は、サーバーのログにだけ残す。
    """
    if isinstance(exc, LLMError):
        return "AI の呼び出しに失敗しました。時間をおいて再度お試しください"
    if isinstance(exc, SearchError):
        return "Web 検索に失敗しました。時間をおいて再度お試しください"
    return "予期しないエラーが発生しました"


# --------------------------------------------------------------------------
# 各ステップ（TODO: stub を実処理へ差し替える）
# --------------------------------------------------------------------------


def _analyze_goal(profile: UserProfile) -> GoalAnalysisOutput:
    """① Goal Analysis"""
    if get_settings().agent_stub_mode:
        return GoalAnalysisOutput(**stub_data.STUB_GOAL_ANALYSIS)

    return analyze_goal(
        GoalAnalysisInput(
            occupation=profile.occupation,
            skills=profile.skills or [],
            interests=profile.interests or [],
            goals=profile.goals or [],
            about=profile.about,
        )
    )


def _plan_search(state: AgentState, profile: UserProfile) -> list[SearchDirection]:
    """② Search Planning"""
    if get_settings().agent_stub_mode:
        return [SearchDirection(**d) for d in stub_data.STUB_SEARCH_DIRECTIONS]

    goal = state.goal_analysis
    if goal is None:  # 順序を崩した呼び出しへの保険
        raise RuntimeError("goal analysis の前に search planning を呼んでいます")

    win = search_window.SearchWindow.from_dict(state.search_window)
    return plan_search(
        goal_summary=goal.goal_summary,
        goal_directions=goal.goal_directions,
        interest_connections=goal.interest_connections,
        location=profile.location,
        # **run 開始時に確定した期間**を明示して渡す（#47）。
        window=(f"{win.start:%Y年%m月%d日}〜{win.end:%Y年%m月%d日}" if win else None),
    )


def _search_and_extract(db: Session, state: AgentState) -> list[str]:
    """Web Search Tool + ③ Opportunity Extraction。発見した opportunity_id を返す。"""
    if get_settings().agent_stub_mode:
        ids: list[str] = []
        for raw in stub_data.STUB_OPPORTUNITIES:
            row = _upsert_opportunity(db, state, raw)
            ids.append(row.opportunity_id)
            time.sleep(0.4)  # 探索中画面が見えるように少しずつ進める
        if get_settings().demo_injection:
            _demo_attack_without_llm(db, state)
        state.discovered_ids = ids
        return ids

    # --- ① まず全方向を検索する。検索は速いので方向ごとに回してよい ---------
    seen: set[str] = set()
    candidates = []  # (探索方向, SearchResult)
    for direction in state.search_directions:
        try:
            with cost.step("search"):
                found = registry.invoke(
                    "search_web", query=direction.query, limit=MAX_RESULTS_PER_DIRECTION
                ).data
        except SearchError as exc:
            # 1 方向の失敗で探索全体を止めない。他の方向はまだ試せる。
            _log(db, state, AgentStep.SEARCHING, f"「{direction.query}」の検索に失敗しました")
            logger.warning("search.failed query_len=%d reason=%s", len(direction.query), exc)
            continue

        # 同じ催しが複数の方向から見つかる。URL で重複を除く。
        fresh = [r for r in found if r.url not in seen]
        seen.update(r.url for r in fresh)
        if not fresh:
            _log(db, state, AgentStep.SEARCHING, f"「{direction.query}」は既出のみでした")
            continue
        candidates.extend((direction, r) for r in fresh)

    if get_settings().demo_injection and state.search_directions:
        # 攻撃デモ（#52）。以降の検知・除去・推薦から外す判断は本番と同じ経路を通る。
        candidates.append((state.search_directions[0], demo_attack.search_result()))
        _log(db, state, AgentStep.SEARCHING, demo_attack.LOG_MESSAGE)

    if not candidates:
        state.discovered_ids = []
        return []

    # **検索で見つかった候補を run に残す（#47）。**
    # 粗選別より前に保存するので、読まなかった分も含めて全件が残る。
    # 結果画面の一覧がこれを使う。**本文は保存しない。**
    _save_search_candidates(db, state, candidates)

    # --- ② 本文の指示らしき文を取り除く -------------------------------------
    # **LLM に渡す前にコードで取り除く（#27）。** 読む候補を選ぶ Jev も
    # 検索結果の文を読むので、優先順位を付けるより先に通す。
    candidates = _guard_candidates(db, state, candidates)

    # --- ③ 読む候補を決める --------------------------------------------------
    # 構成 A（既定）は全件読む。構成 C は読む前に優先順位を付ける。
    candidates, deferred = _choose_what_to_read(db, state, candidates)

    # --- ④ 本文が無い候補は取りに行く ---------------------------------------
    # **Serper は snippet しか返さない。** 検索 provider を替えただけでは
    # 抽出の入力が痩せるため、本文取得を別に走らせる。
    # 取ってきた本文も Web 由来。抽出へ渡す前に検査する。
    sources = _guard_bodies(db, state, _with_bodies([r for _, r in candidates]))

    # --- ⑤ 全候補をまとめて抽出する -----------------------------------------
    # **方向ごとに抽出すると方向の数だけ待ち時間が積み上がる。**
    # 実測では方向ごとだと 137 秒、まとめると 1 方向分の時間で済む。
    with cost.step("extraction"):
        extracted, failed = extract_many(sources)

    # 読んだ結果、候補がほとんど残らなかったときは後回しにした分から足す。
    # **上限を設ける。無制限には増やさない。**
    if deferred and len(extracted) < TOP_N:
        extra = deferred[: get_settings().prefilter_extra_reads]
        _log(db, state, AgentStep.SEARCHING, f"候補が足りないため{len(extra)}件を追加で読みます")
        with cost.step("extraction"):
            more, more_failed = extract_many(
                _guard_bodies(db, state, _with_bodies([r for _, r in extra]))
            )
        extracted = [*extracted, *more]
        failed = [*failed, *more_failed]
        candidates = [*candidates, *extra]
        cost.record_dropped("prefilter_extra_reads", len(extra))

    # クエリ文字列ではなく**方向の位置**を鍵にする。LLM が同じ query を持つ方向を
    # 2 つ返すことがあり、文字列で集計すると件数が合算されて二重に表示される。
    order = {id(d): i for i, d in enumerate(state.search_directions)}
    by_url = {r.url: order[id(direction)] for direction, r in candidates}

    ids: list[str] = []
    per_direction: dict[int, int] = {}
    for source_url, item in extracted:
        row = _save_extracted(db, state, item, source_url)
        ids.append(row.opportunity_id)
        if source_url in state.flagged_urls:
            state.flagged_ids.add(row.opportunity_id)
        # 本文取得で URL が変わることは無いが、追加読み込み分が by_url に
        # 無い可能性はある。**KeyError で run を落とさない。**
        index = by_url.get(source_url)
        if index is None:
            continue
        per_direction[index] = per_direction.get(index, 0) + 1

    # --- ③ 探索方向ごとに結果を伝える（画面に出る単位を保つ）-----------------
    for index, direction in enumerate(state.search_directions):
        count = per_direction.get(index, 0)
        if count:
            _log(
                db,
                state,
                AgentStep.SEARCHING,
                f"「{direction.query}」から{count}件を読み取りました",
            )
    if failed:
        # 取れなかった事実は隠さない。
        _log(db, state, AgentStep.SEARCHING, f"{len(failed)}件は読み取れませんでした")

    state.discovered_ids = ids
    return ids


def _choose_what_to_read(db: Session, state: AgentState, candidates: list) -> tuple[list, list]:
    """読む候補と、後回しにする候補に分ける。

    既定（`SEARCH_PIPELINE=full`）は**全件読む。現行の挙動を変えない。**

    `prefilter` のときは Jev に粗い見立てをさせ、上位だけを読む。
    **後回しにした分も順に並べて返す。** 読んだ結果 3 件に満たなかったとき、
    先頭から追加で読めるようにするため。
    """
    settings = get_settings()
    if settings.search_pipeline.strip().lower() != "prefilter":
        return candidates, []

    limit = max(1, settings.prefilter_read_limit)
    if len(candidates) <= limit:
        return candidates, []

    goal = state.goal_analysis
    # **探索方向を渡す。** 渡さないと関連性順だけで並び、方向がまるごと
    # 消える（実測で 4 方向のうち 2 方向が 1 件も読まれなかった）。
    order = {id(d): i for i, d in enumerate(state.search_directions)}
    with cost.step("prefilter"):
        selected, rest = rank_for_reading(
            [r for _, r in candidates],
            goal_summary=goal.goal_summary if goal else "",
            interest_connections=goal.interest_connections if goal else [],
            limit=limit,
            directions=[order[id(d)] for d, _ in candidates],
        )

    _log(
        db,
        state,
        AgentStep.SEARCHING,
        f"{len(candidates)}件の候補から{len(selected)}件を詳しく読みます",
    )
    cost.record_dropped("prefilter_deferred", len(rest))
    return [candidates[i] for i in selected], [candidates[i] for i in rest]


def _with_bodies(results: list[SearchResult]) -> list[SearchResult | PageContent]:
    """本文が無い候補だけ取りに行く。

    Tavily の検索は 800〜1500 文字の本文抜粋を返すので、そのまま使える。
    **Serper は snippet しか返さない。** 検索 provider を替えただけでは
    抽出の入力が痩せるため、ここで本文取得（`tools/fetch/`）を挟む。

    **取得できなかった候補は捨てない。** snippet だけでも抽出は試せる。
    全文が取れたことと、期限を確認できたことは別（申込先の別ページにしか
    締切が無いことがある）なので、取得成功を確認済みとは扱わない。

    **取ってきた本文は `_guard_bodies` に通してから渡す（#27）。**
    """
    need = [r for r in results if not r.content]
    if not need:
        return list(results)

    with cost.step("fetch"):
        try:
            out = registry.invoke("read_page", url=[r.url for r in need]).data
        except SearchError as exc:
            # 本文が取れなくても snippet で続ける。探索全体は止めない。
            logger.warning("fetch.failed reason=%s", exc)
            return list(results)

    pages = {p.url: p for p in out["pages"]}
    merged: list[SearchResult | PageContent] = []
    for r in results:
        page = pages.get(r.url)
        merged.append(page if page is not None else r)
    return merged


def _save_search_candidates(db: Session, state: AgentState, candidates: list) -> None:
    """検索で見つかった候補を run に残す。**タイトルと URL だけ。**

    再読み込みしても一覧を出せるようにするため。本文を残すと、取得元の
    利用条件に関わるうえ DB も膨らむので、残さない。
    """
    order = {id(d): i for i, d in enumerate(state.search_directions)}
    rows = [
        {"title": r.title, "url": r.url, "direction": order.get(id(direction))}
        for direction, r in candidates
    ]
    run = db.get(AgentRun, state.run_id)
    if run is not None:
        run.search_candidates = rows
        db.commit()
    _log(db, state, AgentStep.SEARCHING, f"検索で{len(rows)}件の候補が見つかりました")


def _guard_bodies(
    db: Session, state: AgentState, sources: list[SearchResult | PageContent]
) -> list[SearchResult | PageContent]:
    """取ってきた本文も LLM に渡す前に検査する（#27）。

    `_guard_candidates` が見たのは検索結果の snippet までで、**本文は取得の後に
    届く。** ここを通さないと、構成 C（Serper + Jina）では指示らしき文が
    そのまま抽出の LLM に届く。検索結果のままの候補は検査済みなので触らない。
    """
    guarded: list[SearchResult | PageContent] = []
    flagged = 0
    kinds: set[str] = set()
    for source in sources:
        if not isinstance(source, PageContent):
            guarded.append(source)
            continue
        inspected = guard.inspect(source.content)
        if inspected.suspicious:
            state.flagged_urls.add(source.url)
            flagged += 1
            kinds.update(inspected.findings)
        guarded.append(replace(source, content=inspected.text))
    if flagged:
        _log(
            db,
            state,
            AgentStep.SEARCHING,
            f"{flagged}件のページで指示らしき文を見つけ、取り除いてから読みました",
        )
        # 本文は出さない。種類と件数だけ残す。
        logger.warning("guard.flagged stage=fetch count=%d kinds=%s", flagged, sorted(kinds))
    return guarded


def _guard_candidates(
    db: Session,
    state: AgentState,
    candidates: list[tuple[SearchDirection | None, SearchResult]],
) -> list[tuple[SearchDirection | None, SearchResult]]:
    """検索結果の本文を検査し、指示らしき文を取り除いた候補を返す（#27）。

    **LLM に届く前に取り除く。** プロンプトの規則だけに頼らない。
    見つけたページの URL は `state.flagged_urls` に残す（推薦しない判断に使う）。

    URL も検査する。抽出の LLM には取得元 URL も渡る（`ai/prompts/extraction`）ため、
    `/ignore-all-previous-instructions` のようにパスへ書いた指示も届く。URL は候補の
    鍵なので書き換えず、見つけたら推薦しないだけにする。%エンコードは戻してから調べる。
    """
    guarded = []
    kinds: set[str] = set()
    for direction, r in candidates:
        content = guard.inspect(r.content)
        snippet = guard.inspect(r.snippet)
        url = guard.inspect(unquote_plus(r.url))
        if content.suspicious or snippet.suspicious or url.suspicious:
            state.flagged_urls.add(r.url)
            kinds.update(content.findings, snippet.findings, url.findings)
        cleaned = replace(
            r,
            content=content.text if r.content is not None else None,
            snippet=snippet.text,
        )
        guarded.append((direction, cleaned))

    flagged = {r.url for _, r in candidates} & state.flagged_urls
    if flagged:
        _log(
            db,
            state,
            AgentStep.SEARCHING,
            f"{len(flagged)}件のページで指示らしき文を見つけ、取り除いてから読みました",
        )
        # 本文は出さない。種類と件数だけ残す。
        logger.warning("guard.flagged count=%d kinds=%s", len(flagged), sorted(kinds))
    return guarded


def _demo_attack_without_llm(db: Session, state: AgentState) -> None:
    """固定データの経路（AGENT_STUB_MODE）で攻撃デモを見せる（#52）。

    LLM を呼ばない経路なので抽出と評価は無いが、**検知と「推薦しない」判断は
    本番と同じコード**（`_guard_candidates`）で行う。API が使えない場でも
    防御の流れを見せられるようにするため。
    """
    _log(db, state, AgentStep.SEARCHING, demo_attack.LOG_MESSAGE)
    page = demo_attack.search_result()
    _guard_candidates(db, state, [(None, page)])
    if page.url in state.flagged_urls:
        _log(db, state, AgentStep.SEARCHING, _DROPPED_MESSAGE)


def _save_extracted(
    db: Session,
    state: AgentState,
    item: ExtractedOpportunity,
    source_url: str,
) -> Opportunity:
    """抽出結果を Opportunity として保存する。

    同じ URL を過去の run でも拾っている場合は、その行を使い回す。
    run のたびに同じ催しが増えないようにするため。

    **既存の行の事実を書き換えてよいのは、その行のページ（か配下）を読んだときだけ。**
    connpass のような誰でも書けるサイトでは、別のページに「申込: connpass.com/event/1」
    と書くだけで、ユーザーが「興味あり」にした催しの日時や場所を差し替えられるため。
    """
    item = _without_links(item)
    flagged = source_url in state.flagged_urls
    if flagged:
        # 指示らしき文があったページの申込先は採らない。採ると、そのページの
        # フラグ（行の id に付く）が別の正当な催しの行に付き、推薦から外れてしまう。
        url = source_url
    else:
        url = _trusted_url(item.url, source_url, db=db, state=state, title=item.title)
    # **抽出の時点では申込先を確認できていない。**
    #
    # 以前は「同じサイトなら申込先」としていたが、**同一サイトであることは
    # 根拠にならない。** 外部の申込サービス（Google Form、Peatix、connpass）を
    # 使う催しは多く、逆に同じサイトでも申込ページとは限らない。
    #
    # 申込先と言えるのは、⑦ 検証で**本文から導線を読み取れた**ときだけ。
    url_is_source_only = True
    row = None
    if url:
        row = (
            db.query(Opportunity)
            .filter(Opportunity.user_id == state.user_id, Opportunity.url == url)
            .first()
        )
    if row is None:
        row = Opportunity(opportunity_id=f"opp_{uuid.uuid4().hex[:12]}")
        db.add(row)
    elif flagged or not _owns(source_url, url):
        # 行は使い回すが、事実は前のまま。指示らしき文があったページの抽出結果でも
        # 上書きしない（画面に出ている「興味あり」の行を書き換えさせない）。
        return row

    # ① Web から取得した事実。取れなかった項目は null のまま入れる。
    row.user_id = state.user_id
    row.run_id = state.run_id
    row.type = item.type
    row.title = item.title
    row.description = item.description
    row.url = url
    row.source = _domain_of(url)
    row.start_at = item.start_at
    row.end_at = item.end_at
    row.deadline = item.deadline
    row.location = item.location
    row.format = item.format
    row.eligibility = item.eligibility
    row.cost = item.cost
    # **何に対する締切・料金か。** ページ全体の受付状況を一括で決めないため。
    row.deadline_kind = item.deadline_kind
    row.deadline_quote = item.deadline_quote
    row.cost_kind = item.cost_kind
    row.recommended_action = item.recommended_action
    row.url_is_source_only = url_is_source_only
    row.start_at_is_date_only = item.start_at_is_date_only
    row.end_at_is_date_only = item.end_at_is_date_only
    row.deadline_is_date_only = item.deadline_is_date_only

    # ② AI の評価はこの時点では付けない（④ Evaluation の責務）。
    if row.status is None:
        row.status = OpportunityStatus.DISCOVERED

    db.commit()
    return row


def _without_links(item: ExtractedOpportunity) -> ExtractedOpportunity:
    """画面に出る自由文から URL・メール・電話番号を取り除く（#77）。

    行き先として見せるのは、検索結果と照合した `url` だけにする。
    """
    fields = ("title", "description", "location", "eligibility")
    return item.model_copy(update={f: guard.strip_links(getattr(item, f)) for f in fields})


def _trusted_url(
    extracted: str | None,
    source_url: str,
    *,
    db: Session,
    state: AgentState,
    title: str,
) -> str:
    """保存する URL を決める。**信頼の起点は検索でヒットした URL。**

    `extracted` は LLM がページ本文から読み取った申込先で、**ページの書き手が
    自由に決められる**。これをそのまま採用すると、⑦ Verification が
    「公式ページ」として読みに行く先まで書き手に握られ、検証が成立しない。

    同じドメインのときだけ採用し、違えば取得元を使う。告知ページと申込先が
    別ドメインという正当なケースは拾えなくなるが、**検証できない URL を
    公式として見せるより、確認できたページへ誘導するほうが安全**と判断した。
    """
    if not extracted or _same_site(extracted, source_url):
        return extracted or source_url

    # 黙って捨てない。食い違ったという事実を残す。
    _log(
        db,
        state,
        AgentStep.SEARCHING,
        f"「{title}」の申込先が検索結果と別ドメインのため、取得元のページを使います",
    )
    return source_url


def _same_site(a: str, b: str) -> bool:
    """同じサイトとみなせるか。

    サブドメインの違いは許す（`events.connpass.com` と `connpass.com`）。

    **裸の TLD を親ドメインとして扱わない。** `com` と `connpass.com` を
    同一サイトと判定すると、LLM が `https://com/...` を返しただけで
    どんな `*.com` とも一致してしまう。ラベルが 2 つ未満のホストは
    親ドメインの側に立てない。

    Public Suffix List は見ていないため `co.jp` のような 2 段の接尾辞は
    ラベル数 2 として通る。`example.co.jp` が `co.jp` の子として扱われる
    ケースは残る。厳密にやるなら PSL が要るが、依存を増やさない判断。
    """
    host_a = _host(a)
    host_b = _host(b)
    if not host_a or not host_b:
        return False
    if host_a == host_b:
        return True
    # 親側になれるのはラベルを 2 つ以上持つホストだけ
    if _labels(host_b) >= 2 and host_a.endswith(f".{host_b}"):
        return True
    return _labels(host_a) >= 2 and host_b.endswith(f".{host_a}")


def _owns(page: str, url: str) -> bool:
    """`page` を読んだ結果で、`url` の行の事実を書き換えてよいか。

    同じページか、その配下（`/event/1` に対する `/event/1/join`）のときだけ。
    同じサイトの別ページ（`/event/999`）は、書き手が別人でありうるので含めない。

    - **同じページかは `?` 以降まで比べる。** `event.php?id=1` と `event.php?id=999` は
      パスが同じでも別の催し
    - **トップページ（`/`）は配下を持たない。** 持たせると、そのサイトの全ページが
      配下になり、一覧に並んだ別の催しの情報で既存の行を書き換えられてしまう
    """
    host = _host(page)
    if not host or host != _host(url):
        return False
    try:
        p, u = urlparse(page), urlparse(url)
    except ValueError:
        return False
    base = p.path.rstrip("/")
    if u.path.rstrip("/") == base and u.query == p.query:
        return True
    return bool(base) and u.path.startswith(f"{base}/")


def _host(url: str) -> str | None:
    """ホスト名（小文字・末尾の . なし）。**壊れた URL では例外を投げず None。**

    申込先の URL は LLM がページ本文から読み取った値で、書き手が自由に決められる。
    `http://[::1./x` のような値で `urlparse` は ValueError を投げるため、
    ここで受けないと 1 ページの細工で run 全体が失敗する。
    """
    try:
        host = urlparse(url).hostname
    except ValueError:
        return None
    return host.lower().rstrip(".") if host else None


def _labels(host: str) -> int:
    return len([x for x in host.split(".") if x])


def _domain_of(url: str | None) -> str | None:
    """発見元の表示用。例: connpass.com"""
    if not url:
        return None
    try:
        return urlparse(url).netloc or None
    except ValueError:
        return None


# 検証にかける件数の上限。**時間そのものは保証できない**（実行中の通信を
# 中断できないため）。件数で抑える。
MAX_VERIFY = 5
MAX_PROMOTIONS = 2


def _evaluate_and_select(db: Session, state: AgentState, ids: list[str]) -> list[str]:
    """④ Evaluation + ⑤ 順位付け。**検証と推薦理由はここでは行わない。**

    処理順を変えた（#68）。

        抽出 -> 明確な期限切れを除外 -> 評価・順位付け
        -> 上位を検証 -> 終了候補を除外 -> 次順位を追加検証
        -> 最終候補にだけ推薦理由 -> 結果保存

    推薦理由を検証の後に移したのは、**終了した候補の理由を書かずに済ませる**
    ためと、警告を理由へ織り込めるようにするため。
    **これで費用が必ず減るとは限らない**（繰り上げの追加検証が増える）。
    """
    if get_settings().agent_stub_mode:
        rows = (
            db.query(Opportunity)
            .filter(Opportunity.opportunity_id.in_(ids))
            .order_by(Opportunity.score.desc())
            .limit(3)
            .all()
        )
        db.commit()
        # **状態の更新は _verify_and_finalize に任せる**（実経路と同じ形にする）。
        state.ranked_ids = [r.opportunity_id for r in rows]
        return state.ranked_ids

    goal = state.goal_analysis
    if goal is None:  # 順序を崩した呼び出しへの保険
        raise RuntimeError("goal analysis の前に evaluation を呼んでいます")
    if not ids:
        return []

    rows = {
        r.opportunity_id: r
        for r in db.query(Opportunity).filter(Opportunity.opportunity_id.in_(ids)).all()
    }

    # 指示らしき文があったページの候補は、評価にも推薦にも回さない（#77）。
    # 取り除いた後の本文でも、書き手が推薦を操作しようとした事実は残る。
    for opportunity_id in sorted(state.flagged_ids & rows.keys()):
        _drop_flagged(db, state, rows.pop(opportunity_id), AgentStep.EVALUATING)

    # --- 評価の前に落とす ---------------------------------------------------
    candidates = _drop_before_evaluation(db, state, rows)
    if not candidates:
        return []

    # --- ④ 評価する ---------------------------------------------------------
    with cost.step("evaluation"):
        evaluated, failed = evaluate_many(
            goal_summary=goal.goal_summary,
            interest_connections=goal.interest_connections,
            opportunities=[_as_dict(rows[i]) for i in candidates],
        )
    for opportunity_id, out in evaluated:
        row = rows[opportunity_id]
        row.score = out.score
        row.serendipity_score = out.serendipity_score
        # **None は「この評価器は語句を作らない」という意味。**
        # Jev は文字列を生成しないので、埋めるものが無い。当たり障りのない語で
        # 埋めると LLM が挙げた根拠と見分けがつかなくなるため、空のまま残す。
        # どちらの評価器だったかは run の usage に残る（evaluator）。
        if out.match_reasons is None:
            row.match_reasons = []
            cost.record_dropped("reasons_not_generated")
        else:
            # 根拠はそのまま画面に出る。連絡先を載せない（#77）。
            row.match_reasons = [guard.strip_links(m) for m in out.match_reasons]
    db.commit()

    # 比較（#65）で結果の出どころを追えるようにする。
    if evaluated:
        cost.record_evaluator(evaluated[0][1].evaluator, evaluated[0][1].evaluator_model)

    if failed:
        # 評価できなかった事実を隠さない。
        cost.record_dropped("evaluation_failed", len(failed))
        _log(db, state, AgentStep.EVALUATING, f"{len(failed)}件は評価できませんでした")

    # --- ⑤ 順位付け（LLM を使わない）----------------------------------------
    state.ranked_ids = select_top(evaluated, limit=len(evaluated))
    return state.ranked_ids


def _drop_before_evaluation(
    db: Session, state: AgentState, rows: dict[str, Opportunity]
) -> list[str]:
    """評価より前に、**確実に対象外と分かるものだけ**落とす。

    落とすのは 2 種類。

      - ユーザーが自分で外した（dismissed）
      - 日時から**受付終了と言い切れる**（deadline / end_at が過去）

    **不明は落とさない。** deadline が null は「受付終了でも受付中でもない」。
    `start_at` が過去でも落とさない（開始済みでも参加できる機会がある）。
    """
    kept: list[str] = []
    dismissed = 0
    closed = 0

    for opportunity_id, row in rows.items():
        if row.status == OpportunityStatus.DISMISSED:
            dismissed += 1
            continue

        # **共通の入口を通す。** 引数の組み立てを呼び出し側で繰り返さない。
        # 繰り返すと、どれか 1 つで項目が抜ける（実際に抜けた）。
        status, reason = availability.for_extracted(row)
        if status is availability.Availability.CLOSED:
            _set_availability(row, status, reason, source=None)
            closed += 1
            # **区分を確認できていない旧い行は、別に数える。**
            # 確認済みのものと同じ確かさで扱われていないかを後から見るため。
            if row.deadline_kind is None:
                cost.record_dropped("closed_by_date_unclassified")
            continue
        # 閉じないが理由が付いた場合（早割の期限だった等）も残す。
        # **理由を捨てると、なぜ受付中扱いなのかが後から読めない。**
        if reason:
            _set_availability(row, status, reason, source=None)
        kept.append(opportunity_id)

    db.commit()

    if dismissed:
        cost.record_dropped("dismissed", dismissed)
    if closed:
        cost.record_dropped("closed_by_date", closed)
        _log(db, state, AgentStep.EVALUATING, f"{closed}件は期限切れのため評価しませんでした")
    return kept


def _verified_availability(row: Opportunity, out) -> tuple[str, str | None]:
    """検証の結果を、締切の区分と突き合わせてから採る。

    **検証はページ文言だけで open / closed を決めている。** 渡しているのは
    `_as_dict` の中身（title / start_at / deadline / location / cost）で、
    `deadline_kind` は入っていない。

    そのため、取り消し線つきの「応募を締め切りました」（登壇者募集）を拾って
    `closed` を返しうる。**抽出段階で `unknown` に倒したはずの判断が、
    最後の一歩で誤って閉じられる。**

    閉じる向きだけを見張る。**開ける向きは触らない**（検証はページを読んで
    いるので、`open` の根拠は抽出時より確かなことが多い）。
    """
    if out.availability != availability.Availability.CLOSED:
        return out.availability, out.availability_reason

    # 日付から閉じられるなら、検証の closed と食い違わない。そのまま採る。
    from_dates, _ = availability.for_extracted(row)
    if from_dates is availability.Availability.CLOSED:
        return out.availability, out.availability_reason

    # **見張るのは「過ぎた締切を読み違えた」場合だけ。**
    #
    # 早割や登壇者募集の締切が**過ぎている**と、検証がその終了告知
    # （取り消し線つきの「応募を締め切りました」など）を拾って `closed` を
    # 返しやすい。それが狙った不具合。
    #
    # 締切が**まだ来ていない**なら、検証の `closed` はその締切の話ではない
    # （満員・中止など、ページを読んで初めて分かること）。**そちらは倒さない。**
    # 倒すと、実際に確かめた観察を捨てることになる。
    #
    # **`availability._is_past` とはわざと違う判定を使う。**
    #
    #   あちら  締切を過ぎたかどうか。日付だけの締切は**当日中は過ぎていない**
    #           （00:00 はこちらの正規化で、出典の時刻ではないため）
    #   ここ    検証が読み違えうる「終了っぽい日付」が近くにあるか
    #
    # 当日が期限の日付だけの締切も、ページには終了告知が載りうる。
    # **こちらは広く取る。** 広く取ると `unknown` へ倒れる側に外れるので、
    # 誤って閉じることはない。
    #
    # ここを `_is_past` に揃えると、当日のぶんが `closed` を素通しする側へ
    # 倒れる。**揃えないこと自体が意図。**
    # **検証自身が「参加の締切」と言っているなら、倒さない。**
    #
    # 実測で、申込締切が 2023 年 12 月のアクセラレーターが推薦に残った。
    # 検証は「申込の締切が過ぎています」と書いていたのに、抽出段階で
    # `deadline_kind` を `unknown` にしか倒せなかったために、この見張りが
    # 「参加の締切か確認できない」として `unknown` へ戻していた。
    #
    # **古い日付だから閉じるのではない。** 検証が読み取った終了の根拠が、
    # 推薦する行動（応募・参加登録）に対応する締切や開催終了を指しているか
    # で決める。指していなければ従来どおり `unknown` へ倒す。
    # **区分が分かっているときは、そちらを優先する。** 早割・登壇者募集と
    # 分類できているなら、検証が何と書いていようと参加は塞がれていない。
    # 検証の文言に頼るのは、抽出が区分を決められなかったときだけ。
    if row.deadline_kind in (None, DeadlineKind.UNKNOWN.value) and _closes_the_recommended_action(
        out
    ):
        return out.availability, out.availability_reason

    if (
        row.deadline is not None
        and row.deadline_kind not in _GATING_KINDS
        and availability.as_utc(row.deadline) < datetime.now(UTC)
    ):
        return (
            availability.Availability.UNKNOWN,
            "公式ページに終了を示す記述がありましたが、"
            "それが参加の締切かどうかを確認できませんでした",
        )
    return out.availability, out.availability_reason


# 検証が書いた終了の根拠のうち、**推薦する行動を塞ぐもの**。
#
# 「早割の締切」「登壇者募集の締切」は参加を塞がないので入れない。
# ここに無い語しか出てこなければ、従来どおり `unknown` へ倒す。
_ACTION_CLOSING = (
    "申込の締切",
    "申込締切",
    "応募の締切",
    "応募締切",
    "募集の締切",
    "募集締切",
    "参加申込",
    "参加登録",
    "受付を終了",
    "受付終了",
    "募集を終了",
    "募集は終了",
    "応募を締め切",
    "申込を締め切",
    "開催が終了",
    "開催は終了",
    "終了しました",
)

# **「早割」「登壇」が付いていたら採らない。** 参加そのものは塞がない。
_NOT_ACTION_CLOSING = ("早割", "早期割引", "early bird", "登壇者", "発表者", "cfp", "スピーカー")


def _closes_the_recommended_action(out) -> bool:
    """検証の根拠が、推薦する行動を塞いでいるか。

    見るのは検証が書いた文だけ。**日付の古さでは決めない。**
    """
    text = " ".join(filter(None, [out.availability_reason, *getattr(out, "warnings", [])])).lower()
    if any(w in text for w in _NOT_ACTION_CLOSING):
        return False
    return any(w.lower() in text for w in _ACTION_CLOSING)


def _set_availability(
    row: Opportunity, status: str, reason: str | None, *, source: str | None
) -> None:
    """受付状況を**今回確認した結果として**書く。

    確認日時と取得元を必ず一緒に更新する。**古い open を今回の結果として
    返さない**ため、読む側は checked_at と対で見る。
    """
    row.availability = status
    row.availability_reason = reason
    row.availability_checked_at = datetime.now(UTC)
    row.availability_source = source


def _as_dict(row: Opportunity) -> dict:
    """LLM へ渡す形。ORM オブジェクトをそのまま渡さない。"""
    return {
        "opportunity_id": row.opportunity_id,
        "title": row.title,
        "type": row.type,
        "description": row.description,
        "location": row.location,
        "format": row.format,
        "start_at": row.start_at.isoformat() if row.start_at else None,
        "deadline": row.deadline.isoformat() if row.deadline else None,
        "eligibility": row.eligibility,
        "cost": row.cost,
        "source": row.source,
    }


def _verify_and_finalize(db: Session, state: AgentState) -> None:
    """⑦ 検証 -> 終了候補を除外 -> 次順位を追加検証 -> 推薦理由 -> 結果保存。

    **繰り上げは既存の候補からのみ。** Web の再検索は #22 として分離する。
    """
    if get_settings().agent_stub_mode:
        _verify_stub(db, state)
        return

    ranked = list(state.ranked_ids)
    final: list[str] = []
    checked = 0
    promotions = 0

    no_action = 0

    # 公式ページも Web 由来。LLM に渡す前に指示らしき文を取り除く（#27）。
    # 見つけた URL はここに貯め、**この関数の最後に state へ移す。**
    flagged: set[str] = set()

    def fetch(url: str) -> str | None:
        content = _fetch_page(url)
        if content is None:
            return None
        inspected = guard.inspect(content)
        if inspected.suspicious:
            flagged.add(url)
        return inspected.text

    while ranked and len(final) < TOP_N and checked < MAX_VERIFY:
        opportunity_id = ranked.pop(0)
        row = db.get(Opportunity, opportunity_id)
        if row is None:
            continue

        # **推薦する行動を特定できないものは出さない。**
        #
        # 他人の投稿作品、終了した催しのレポート、解説記事、検索一覧。
        # どれも「応募できる機会」ではない。**type では決めない**ので、
        # 解説記事でも募集先が読み取れていれば通る。
        #
        # 検証より前に外す。**確認に 1 回ぶんの費用をかけない。**
        if not row.recommended_action:
            no_action += 1
            continue

        with cost.step("verification"):
            out = verify_with_page(opportunity=_as_dict(row), url=row.url, fetch_page=fetch)
        checked += 1

        if row.url in flagged:
            # 推薦候補に選んだ後で見つかっても、推薦のままにしない（#77）。
            # **タイトルも確認結果も警告も Log に出さない。** 警告はそのページを
            # LLM が読んで書いた文で、書き手の文が混ざりうる。同じ理由で
            # 「確認済み」にもしない。
            row.verified = False
            _log(db, state, AgentStep.VERIFYING, "推薦候補の公式ページで指示らしき文を見つけました")
            _drop_flagged(db, state, row, AgentStep.VERIFYING)
            db.commit()
            # 受付終了と同じ扱いで次順位を繰り上げる。**1 件減らしたまま終えない。**
            if promotions < MAX_PROMOTIONS and ranked:
                promotions += 1
            continue

        row.verified = out.verified
        row.verified_at = out.verified_at
        row.verification_source = out.verification_source
        # **申込先と言えるのはここだけ。** 本文から導線を読み取れたとき。
        # 取りに行く先ではなく**表示に使う**ので、別サイトでも受け入れる。
        # 画面側で http/https 以外は出さない（`safeHttpUrl`）。
        if out.application_url:
            row.application_url = out.application_url
            row.url_is_source_only = False
        status, reason = _verified_availability(row, out)
        _set_availability(row, status, reason, source=row.url if out.verified else None)
        db.commit()

        _log_verification(db, state, row, out)

        if availability.is_actionable(row.availability):
            final.append(opportunity_id)
            continue

        # 受付終了。**期限切れで 3 件を埋めない。** 次順位を繰り上げる。
        cost.record_dropped("closed_by_verification")
        if promotions < MAX_PROMOTIONS and ranked:
            promotions += 1
            _log(
                db,
                state,
                AgentStep.VERIFYING,
                f"「{row.title}」は受付終了のため、次の候補を確認します",
            )

    state.flagged_urls |= flagged
    state.selected_ids = final
    if no_action:
        cost.record_dropped("no_recommended_action", no_action)
        _log(
            db,
            state,
            AgentStep.VERIFYING,
            f"{no_action}件は記事や一覧のため、応募先を特定できませんでした",
        )
    state.no_action_count = no_action
    state.shortfall_reason = _shortfall_reason(final, state)
    _write_reasons(db, state, final)
    _save_result(db, state)


def _log_verification(db: Session, state: AgentState, row: Opportunity, out) -> None:
    """確認できたことと、受付状況を**分けて**伝える。"""
    if out.verified:
        _log(db, state, AgentStep.VERIFYING, f"「{row.title}」を公式ページで確認しました")
    else:
        _log(db, state, AgentStep.VERIFYING, f"「{row.title}」は確認できませんでした")

    if row.availability == availability.Availability.CLOSED:
        _log(db, state, AgentStep.VERIFYING, f"「{row.title}」: 受付終了を確認しました")
    elif row.availability == availability.Availability.OPEN:
        _log(db, state, AgentStep.VERIFYING, f"「{row.title}」: 受付中を確認しました")

    for warning in out.warnings:
        # 警告も LLM が書いた文。Agent Log として画面に出る（#77）。
        _log(db, state, AgentStep.VERIFYING, f"「{row.title}」: {guard.strip_links(warning)}")


def _shortfall_reason(final: list[str], state: AgentState) -> str | None:
    """3 件に満たない理由。**後から同じ内容を返せるよう run に保存する。**"""
    if len(final) >= TOP_N:
        return None
    if not state.ranked_ids:
        return "条件に合う機会が見つかりませんでした"
    if state.no_action_count:
        return (
            f"応募・参加できる機会が{len(final)}件しか見つかりませんでした"
            f"（{state.no_action_count}件は記事や一覧で、行動の対象を特定できませんでした）"
        )
    if not final:
        return "見つかった機会はいずれも受付を終了していました"
    return f"受付中または要確認の機会が{len(final)}件しか見つかりませんでした"


def _write_reasons(db: Session, state: AgentState, final: list[str]) -> None:
    """**最終候補にだけ**推薦理由を書く。"""
    if not final:
        return
    goals = state.goal_analysis.goal_directions if state.goal_analysis else []
    rows = {i: db.get(Opportunity, i) for i in final}
    targets = {i: _as_dict(r) for i, r in rows.items() if r is not None}

    def one(opportunity_id: str) -> str | None:
        row = rows[opportunity_id]
        if row is None:
            return None
        try:
            reason = recommend(
                goals=goals,
                opportunity=targets[opportunity_id],
                evaluation=EvaluationOutput(
                    score=row.score,
                    serendipity_score=row.serendipity_score,
                    match_reasons=row.match_reasons or [],
                    concerns=[row.availability_reason] if row.availability_reason else [],
                ),
            ).reason
            # 推薦理由はそのまま画面に出る。連絡先を載せない（#77）。
            return guard.strip_links(reason)
        except LLMError as exc:
            # 理由が無くても推薦自体は成立する。run を落とさない。
            logger.warning("recommendation.failed id=%s reason=%s", opportunity_id, exc)
            return None

    with cost.step("recommendation"):
        reasons = map_parallel(final, one)

    for opportunity_id, reason in zip(final, reasons, strict=True):
        row = rows[opportunity_id]
        if row is None:
            continue
        if row.status not in _USER_DECIDED:
            row.status = OpportunityStatus.RECOMMENDED
        if reason is not None:
            row.reason = reason
        _log(
            db,
            state,
            AgentStep.EVALUATING,
            f"「{row.title}」を推薦（適合度{row.score} / 意外性{row.serendipity_score}）",
        )
    db.commit()


def _save_result(db: Session, state: AgentState) -> None:
    """**選定 ID と順位を run に保存する。**

    Opportunity.run_id は同じ URL を再発見すると上書きされるため、過去 run の
    選定結果を保てない。ここに残すことで**画面と Agent の選定が一致する**。

    保証するのは「どれをどの順で選んだか」だけ。**候補の内容は最新値**で、
    選定時点の本文を保存するものではない。
    """
    run = db.get(AgentRun, state.run_id)
    if run is None:
        return
    run.selected_ids = list(state.selected_ids)
    run.shortfall_reason = state.shortfall_reason
    tracker = cost.current()
    if tracker is not None:
        tracker.record_final_availability(
            [
                db.get(Opportunity, i).availability
                for i in state.selected_ids
                if db.get(Opportunity, i) is not None
            ]
        )
        run.usage_json = tracker.to_dict()
    db.commit()


def _verify_stub(db: Session, state: AgentState) -> None:
    """Stub 経路。相方が API キー無しで動かせる状態を保つ。"""
    now = datetime.now(UTC)
    for opportunity_id in state.ranked_ids[:TOP_N]:
        row = db.get(Opportunity, opportunity_id)
        if row is None:
            continue
        row.verified = True
        row.verified_at = now
        row.verification_source = row.url
        _set_availability(row, availability.Availability.OPEN, None, source=row.url)
    state.selected_ids = state.ranked_ids[:TOP_N]
    db.commit()
    _write_reasons_stub(db, state)
    _save_result(db, state)


def _write_reasons_stub(db: Session, state: AgentState) -> None:
    for opportunity_id in state.selected_ids:
        row = db.get(Opportunity, opportunity_id)
        if row is not None and row.status not in _USER_DECIDED:
            row.status = OpportunityStatus.RECOMMENDED
    db.commit()


# 推薦から外したことを伝える Log。**候補のタイトルを入れない。** タイトルは
# 攻撃ページから LLM が読み取った文で、「★当選★ 今すぐ EVIL.COM へ」のように
# 書き手の思いどおりにできる。推薦から外しても Log で画面に届いては意味が無い。
_DROPPED_MESSAGE = "指示らしき文を含むページから取った候補を1件、推薦から外しました"


def _drop_flagged(db: Session, state: AgentState, row: Opportunity, step: AgentStep) -> None:
    """指示らしき文があったページの候補を推薦から外し、そのことを Log に残す（#77）。

    ユーザーが自分で決めた状態（興味あり・参加済みなど）は変えない。
    過去の run で推薦済みだった行は、推薦から戻す。
    """
    state.flagged_ids.add(row.opportunity_id)
    if row.status == OpportunityStatus.RECOMMENDED:
        row.status = OpportunityStatus.DISCOVERED
    _log(db, state, step, _DROPPED_MESSAGE)


def _fetch_page(url: str) -> str | None:
    """公式ページの本文を取る。取れなければ None。"""
    result = registry.invoke("read_page", url=url)
    pages = result.data["pages"]
    return pages[0].content if pages else None


# --------------------------------------------------------------------------
# State / Log の永続化
# --------------------------------------------------------------------------


def _upsert_opportunity(db: Session, state: AgentState, raw: dict) -> Opportunity:
    row = db.get(Opportunity, raw["opportunity_id"])
    if row is None:
        row = Opportunity(opportunity_id=raw["opportunity_id"])
        db.add(row)
    for key, value in raw.items():
        # ユーザーが決めた状態を stub データで潰さない。
        # SEARCH は EVALUATE より前に走るため、ここで潰すと後段のガードが効かない。
        if key == "status" and row.status in _USER_DECIDED:
            continue
        if key in ("start_at", "end_at", "deadline") and isinstance(value, str):
            value = datetime.fromisoformat(value)
        setattr(row, key, value)
    row.user_id = state.user_id
    row.run_id = state.run_id
    db.commit()
    return row


def _step(db: Session, state: AgentState, step: AgentStep, message: str) -> None:
    state.current_step = step
    state.message = message
    state.progress = _PROGRESS.get(step, state.progress)
    if step is AgentStep.COMPLETED:
        state.status = AgentRunStatus.COMPLETED
    _sync(db, state)
    logger.info("agent.step run_id=%s step=%s", state.run_id, step)


def _fail(db: Session, state: AgentState, error: str) -> None:
    state.status = AgentRunStatus.FAILED
    state.message = "探索に失敗しました"
    state.error = error
    _sync(db, state)


def _sync(db: Session, state: AgentState) -> None:
    # 進捗を書くたびに、そこまでの消費量を state へ反映する。
    # 途中で落ちても、そこまでのコストが残る。
    tracker = cost.current()
    if tracker is not None:
        state.cost_jpy = round(tracker.jpy, 4)
        state.expensive_model_calls = tracker.expensive_calls

    run = db.get(AgentRun, state.run_id)
    if run is None:
        return
    run.status = state.status
    run.current_step = state.current_step
    run.message = state.message
    run.progress = state.progress
    run.error = state.error
    run.cost_jpy = state.cost_jpy
    run.expensive_model_calls = state.expensive_model_calls
    db.commit()


def _log(db: Session, state: AgentState, step: AgentStep, message: str) -> None:
    db.add(AgentLog(run_id=state.run_id, step=step, message=message))
    db.commit()
