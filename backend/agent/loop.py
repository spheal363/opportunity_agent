"""Agent Loop。

    PLAN -> SEARCH -> EVALUATE -> REFLECT -> SEARCH AGAIN -> VERIFY -> SELECT

各ステップは AgentRun / AgentLog に進捗を書き出すので、Frontend は
GET /api/agent/runs/{run_id} をポーリングするだけで Agent の行動を表示できる。

現状は AGENT_STUB_MODE=true の経路だけが動く。
LLM / Web Search を実装する後続タスクで、各 _step_* の中身を差し替える。
"""

from __future__ import annotations

import time
from datetime import UTC, datetime

from sqlalchemy.orm import Session

from agent import stub_data
from agent.state import AgentState
from ai.schemas import GoalAnalysisOutput, SearchDirection
from config import get_settings
from db.session import SessionLocal
from logging_config import get_logger
from models import AgentLog, AgentRun, Opportunity, UserProfile
from schemas.agent import AgentRunStatus, AgentStep

logger = get_logger(__name__)

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
        state.search_directions = _plan_search(state)
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
    raise NotImplementedError("goal analysis is not implemented yet")


def _plan_search(state: AgentState) -> list[SearchDirection]:
    """② Search Planning"""
    if get_settings().agent_stub_mode:
        return [SearchDirection(**d) for d in stub_data.STUB_SEARCH_DIRECTIONS]
    raise NotImplementedError("search planning is not implemented yet")


def _search_and_extract(db: Session, state: AgentState) -> list[str]:
    """Web Search Tool + ③ Opportunity Extraction。発見した opportunity_id を返す。"""
    if not get_settings().agent_stub_mode:
        raise NotImplementedError("web search / extraction is not implemented yet")

    ids: list[str] = []
    for raw in stub_data.STUB_OPPORTUNITIES:
        row = _upsert_opportunity(db, state, raw)
        ids.append(row.opportunity_id)
        time.sleep(0.4)  # 探索中画面が見えるように少しずつ進める
    state.discovered_ids = ids
    return ids


def _evaluate_and_select(db: Session, state: AgentState, ids: list[str]) -> list[str]:
    """④ Evaluation + ⑤ TOP3 Selection + ⑥ Recommendation"""
    if not get_settings().agent_stub_mode:
        raise NotImplementedError("evaluation / selection is not implemented yet")

    rows = (
        db.query(Opportunity)
        .filter(Opportunity.opportunity_id.in_(ids))
        .order_by(Opportunity.score.desc())
        .limit(3)
        .all()
    )
    for row in rows:
        row.status = "recommended"
    db.commit()
    return [r.opportunity_id for r in rows]


def _verify(db: Session, state: AgentState) -> None:
    """⑦ Verification"""
    if not get_settings().agent_stub_mode:
        raise NotImplementedError("verification is not implemented yet")

    now = datetime.now(UTC)
    for opportunity_id in state.selected_ids:
        row = db.get(Opportunity, opportunity_id)
        if row is not None:
            row.verified = True
            row.verified_at = now
            row.verification_source = row.url
    db.commit()


# --------------------------------------------------------------------------
# State / Log の永続化
# --------------------------------------------------------------------------


def _upsert_opportunity(db: Session, state: AgentState, raw: dict) -> Opportunity:
    row = db.get(Opportunity, raw["opportunity_id"])
    if row is None:
        row = Opportunity(opportunity_id=raw["opportunity_id"])
        db.add(row)
    for key, value in raw.items():
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
