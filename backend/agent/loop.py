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
from datetime import UTC, datetime
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from agent import stub_data
from agent.state import AgentState
from ai.concurrency import map_parallel
from ai.evaluation import evaluate_many, recommend, select_top
from ai.extraction import extract_many
from ai.goal_analysis import analyze_goal
from ai.llm import LLMError
from ai.schemas import GoalAnalysisOutput, SearchDirection
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
from tools.search.base import SearchError

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
    try:
        state = AgentState(run_id=run_id, user_id=user_id, status=AgentRunStatus.RUNNING)
        profile = db.get(UserProfile, user_id)
        if profile is None:
            _fail(db, state, "プロフィールが登録されていません")
            return

        _step(db, state, AgentStep.ANALYZING_PROFILE, "プロフィールを分析しています")
        state.goal_analysis = _analyze_goal(profile)
        _log(db, state, AgentStep.ANALYZING_PROFILE, state.goal_analysis.goal_summary)

        _step(db, state, AgentStep.PLANNING, "何を探すべきか計画しています")
        state.search_directions = _plan_search(state, profile)
        for d in state.search_directions:
            _log(db, state, AgentStep.PLANNING, f"探索対象に設定: {d.query}（{d.reason}）")

        _step(db, state, AgentStep.SEARCHING, "Webを探索しています")
        found = _search_and_extract(db, state)
        _log(db, state, AgentStep.SEARCHING, f"{len(found)}件のOpportunityを発見")

        _step(db, state, AgentStep.EVALUATING, "Opportunityを評価しています")
        state.selected_ids = _evaluate_and_select(db, state, found)
        _log(
            db,
            state,
            AgentStep.EVALUATING,
            f"{len(found)}件からTOP{len(state.selected_ids)}件に絞り込み",
        )

        _step(db, state, AgentStep.VERIFYING, "TOP3の公式情報を確認しています")
        _verify(db, state)
        _log(db, state, AgentStep.VERIFYING, "TOP3の公式情報を確認しました")

        state.status = AgentRunStatus.COMPLETED
        _step(db, state, AgentStep.COMPLETED, "探索が完了しました")
    except Exception as exc:  # Agent 全体を落とさず run を failed にする
        logger.exception("agent run failed run_id=%s", run_id)
        db.rollback()
        _fail(db, AgentState(run_id=run_id, user_id=user_id), str(exc))
    finally:
        db.close()


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

    # --- ② 全候補をまとめて抽出する -----------------------------------------
    # **方向ごとに抽出すると方向の数だけ待ち時間が積み上がる。**
    # 実測では方向ごとだと 137 秒、まとめると 1 方向分の時間で済む。
    extracted, failed = extract_many([r for _, r in candidates])

    # クエリ文字列ではなく**方向の位置**を鍵にする。LLM が同じ query を持つ方向を
    # 2 つ返すことがあり、文字列で集計すると件数が合算されて二重に表示される。
    order = {id(d): i for i, d in enumerate(state.search_directions)}
    by_url = {r.url: order[id(direction)] for direction, r in candidates}

    ids: list[str] = []
    per_direction: dict[int, int] = {}
    for source_url, item in extracted:
        row = _save_extracted(db, state, item, source_url)
        ids.append(row.opportunity_id)
        index = by_url[source_url]
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


def _evaluate_and_select(db: Session, state: AgentState, ids: list[str]) -> list[str]:
    """④ Evaluation + ⑤ TOP3 Selection + ⑥ Recommendation"""
    if get_settings().agent_stub_mode:
        rows = (
            db.query(Opportunity)
            .filter(Opportunity.opportunity_id.in_(ids))
            .order_by(Opportunity.score.desc())
            .limit(3)
            .all()
        )
        for row in rows:
            if row.status not in _USER_DECIDED:
                row.status = OpportunityStatus.RECOMMENDED
        db.commit()
        return [r.opportunity_id for r in rows]

    goal = state.goal_analysis
    if goal is None:  # 順序を崩した呼び出しへの保険
        raise RuntimeError("goal analysis の前に evaluation を呼んでいます")
    if not ids:
        return []

    rows = {
        r.opportunity_id: r
        for r in db.query(Opportunity).filter(Opportunity.opportunity_id.in_(ids)).all()
    }

    # ④ 全件を評価する
    evaluated, failed = evaluate_many(
        goal_summary=goal.goal_summary,
        interest_connections=goal.interest_connections,
        opportunities=[_as_dict(r) for r in rows.values()],
    )
    for opportunity_id, out in evaluated:
        row = rows[opportunity_id]
        row.score = out.score
        row.serendipity_score = out.serendipity_score
        row.match_reasons = out.match_reasons
    db.commit()

    if failed:
        # 評価できなかった事実を隠さない。
        _log(db, state, AgentStep.EVALUATING, f"{len(failed)}件は評価できませんでした")

    # ⑤ TOP3 を選ぶ（LLM を使わない）
    selected = select_top(evaluated)

    # ⑥ 推薦理由は TOP3 にだけ書く。3 件を直列にすると待ち時間が積み上がる。
    by_id = dict(evaluated)
    goals = state.goal_analysis.goal_directions

    # ORM をワーカースレッドへ渡さない。メインスレッドで dict にしてから渡す
    # （_verify と同じ形）。lazy load がスレッドをまたぐと壊れる。
    targets = {i: _as_dict(rows[i]) for i in selected}

    def one(opportunity_id: str) -> str | None:
        try:
            return recommend(
                goals=goals,
                opportunity=targets[opportunity_id],
                evaluation=by_id[opportunity_id],
            ).reason
        except LLMError as exc:
            # 理由が無くても推薦自体は成立する。run を落とさない。
            logger.warning("recommendation.failed id=%s reason=%s", opportunity_id, exc)
            return None

    reasons = map_parallel(selected, one)

    for opportunity_id, reason in zip(selected, reasons, strict=True):
        row = rows[opportunity_id]
        # ユーザーが「興味なし」にしたものを再探索で推薦へ戻さない。
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
    return selected


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


def _verify(db: Session, state: AgentState) -> None:
    """⑦ Verification。TOP3 の公式ページを見に行き、抽出済みの内容と突き合わせる。

    **TOP3 だけに限る。** 全件の公式ページを取りに行くと read_page も LLM も
    一気に増える。推薦する 3 件だけ裏を取る。
    """
    if get_settings().agent_stub_mode:
        now = datetime.now(UTC)
        for opportunity_id in state.selected_ids:
            row = db.get(Opportunity, opportunity_id)
            if row is not None:
                row.verified = True
                row.verified_at = now
                row.verification_source = row.url
        db.commit()
        return

    rows = [db.get(Opportunity, i) for i in state.selected_ids]
    rows = [r for r in rows if r is not None]
    if not rows:
        return

    # 3 件それぞれが「ページ取得 + LLM 呼び出し」で、直列だと待ち時間が積み上がる。
    # DB への書き込みと Log はこのスレッドでまとめて行う（Session を共有しない）。
    targets = [(_as_dict(r), r.url) for r in rows]
    outs = map_parallel(
        targets,
        lambda t: verify_with_page(opportunity=t[0], url=t[1], fetch_page=_fetch_page),
    )

    for row, out in zip(rows, outs, strict=True):
        row.verified = out.verified
        row.verified_at = out.verified_at
        row.verification_source = out.verification_source

        # 確認できなかったことも、食い違いも隠さない。
        if out.verified:
            _log(db, state, AgentStep.VERIFYING, f"「{row.title}」を公式ページで確認しました")
        else:
            _log(db, state, AgentStep.VERIFYING, f"「{row.title}」は確認できませんでした")
        for warning in out.warnings:
            _log(db, state, AgentStep.VERIFYING, f"「{row.title}」: {warning}")

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
