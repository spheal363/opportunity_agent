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
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from agent import stub_data
from agent.state import AgentState
from ai import availability, cost
from ai.concurrency import map_parallel
from ai.evaluation import TOP_N, evaluate_many, recommend, select_top
from ai.extraction import extract_many
from ai.goal_analysis import analyze_goal
from ai.jev.prefilter import rank_for_reading
from ai.llm import LLMError
from ai.schemas import GoalAnalysisOutput, SearchDirection
from ai.schemas.evaluation import EvaluationOutput
from ai.schemas.extraction import ExtractedOpportunity
from ai.schemas.goal_analysis import GoalAnalysisInput
from ai.search_plan import plan_search
from ai.verification import verify_with_page
from config import get_settings
from db.session import SessionLocal
from logging_config import get_logger
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
        profile = db.get(UserProfile, user_id)
        if profile is None:
            _fail(db, state, "プロフィールが登録されていません")
            return

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
        logger.exception("agent run failed run_id=%s", run_id)
        db.rollback()
        _fail(db, AgentState(run_id=run_id, user_id=user_id), str(exc))


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

    return plan_search(
        goal_summary=goal.goal_summary,
        goal_directions=goal.goal_directions,
        interest_connections=goal.interest_connections,
        location=profile.location,
    )


def _search_and_extract(db: Session, state: AgentState) -> list[str]:
    """Web Search Tool + ③ Opportunity Extraction。発見した opportunity_id を返す。"""
    if get_settings().agent_stub_mode:
        ids: list[str] = []
        for raw in stub_data.STUB_OPPORTUNITIES:
            row = _upsert_opportunity(db, state, raw)
            ids.append(row.opportunity_id)
            time.sleep(0.4)  # 探索中画面が見えるように少しずつ進める
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

    if not candidates:
        state.discovered_ids = []
        return []

    # --- ② 読む候補を決める --------------------------------------------------
    # 構成 A（既定）は全件読む。構成 C は読む前に優先順位を付ける。
    candidates, deferred = _choose_what_to_read(db, state, candidates)

    # --- ③ 本文が無い候補は取りに行く ---------------------------------------
    # **Serper は snippet しか返さない。** 検索 provider を替えただけでは
    # 抽出の入力が痩せるため、本文取得を別に走らせる。
    sources = _with_bodies([r for _, r in candidates])

    # --- ④ 全候補をまとめて抽出する -----------------------------------------
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
            more, more_failed = extract_many(_with_bodies([r for _, r in extra]))
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
    with cost.step("prefilter"):
        selected, rest = rank_for_reading(
            [r for _, r in candidates],
            goal_summary=goal.goal_summary if goal else "",
            interest_connections=goal.interest_connections if goal else [],
            limit=limit,
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


def _save_extracted(
    db: Session,
    state: AgentState,
    item: ExtractedOpportunity,
    source_url: str,
) -> Opportunity:
    """抽出結果を Opportunity として保存する。

    同じ URL を過去の run でも拾っている場合は、その行を使い回す。
    run のたびに同じ催しが増えないようにするため。
    """
    url = _trusted_url(item.url, source_url, db=db, state=state, title=item.title)
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
    row.start_at_is_date_only = item.start_at_is_date_only
    row.end_at_is_date_only = item.end_at_is_date_only
    row.deadline_is_date_only = item.deadline_is_date_only

    # ② AI の評価はこの時点では付けない（④ Evaluation の責務）。
    if row.status is None:
        row.status = OpportunityStatus.DISCOVERED

    db.commit()
    return row


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
    host_a = urlparse(a).hostname
    host_b = urlparse(b).hostname
    if not host_a or not host_b:
        return False
    host_a = host_a.lower().rstrip(".")
    host_b = host_b.lower().rstrip(".")
    if host_a == host_b:
        return True
    # 親側になれるのはラベルを 2 つ以上持つホストだけ
    if _labels(host_b) >= 2 and host_a.endswith(f".{host_b}"):
        return True
    return _labels(host_a) >= 2 and host_b.endswith(f".{host_a}")


def _labels(host: str) -> int:
    return len([x for x in host.split(".") if x])


def _domain_of(url: str | None) -> str | None:
    """発見元の表示用。例: connpass.com"""
    if not url:
        return None
    return urlparse(url).netloc or None


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
            row.match_reasons = out.match_reasons
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

        status, reason = availability.from_dates(
            opportunity_type=row.type,
            deadline=row.deadline,
            end_at=row.end_at,
            # **何に対する締切かで扱いを変える。** 早割の期限が過ぎていても
            # 参加はできる。ここを渡さないと全部を申込締切として閉じてしまう。
            deadline_kind=row.deadline_kind,
            deadline_is_date_only=bool(row.deadline_is_date_only),
        )
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

    while ranked and len(final) < TOP_N and checked < MAX_VERIFY:
        opportunity_id = ranked.pop(0)
        row = db.get(Opportunity, opportunity_id)
        if row is None:
            continue

        with cost.step("verification"):
            out = verify_with_page(opportunity=_as_dict(row), url=row.url, fetch_page=_fetch_page)
        checked += 1

        row.verified = out.verified
        row.verified_at = out.verified_at
        row.verification_source = out.verification_source
        _set_availability(
            row,
            out.availability,
            out.availability_reason,
            source=row.url if out.verified else None,
        )
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

    state.selected_ids = final
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
        _log(db, state, AgentStep.VERIFYING, f"「{row.title}」: {warning}")


def _shortfall_reason(final: list[str], state: AgentState) -> str | None:
    """3 件に満たない理由。**後から同じ内容を返せるよう run に保存する。**"""
    if len(final) >= TOP_N:
        return None
    if not state.ranked_ids:
        return "条件に合う機会が見つかりませんでした"
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
            return recommend(
                goals=goals,
                opportunity=targets[opportunity_id],
                evaluation=EvaluationOutput(
                    score=row.score,
                    serendipity_score=row.serendipity_score,
                    match_reasons=row.match_reasons or [],
                    concerns=[row.availability_reason] if row.availability_reason else [],
                ),
            ).reason
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
