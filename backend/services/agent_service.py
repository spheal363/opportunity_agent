"""Agent Run の作成・状態取得。"""

import uuid

from sqlalchemy.orm import Session

from models import DEFAULT_USER_ID, AgentLog, AgentRun, Opportunity
from schemas.agent import AgentLogEntry, AgentRunResult, AgentRunState, AgentRunStatus
from schemas.opportunity import OpportunitySummary


def create_run(db: Session, user_id: str = DEFAULT_USER_ID) -> str:
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    db.add(AgentRun(run_id=run_id, user_id=user_id, status=AgentRunStatus.QUEUED))
    db.commit()
    return run_id


def get_run(db: Session, run_id: str) -> AgentRunState | None:
    row = db.get(AgentRun, run_id)
    if row is None:
        return None
    return AgentRunState.model_validate(row, from_attributes=True)


def list_logs(db: Session, run_id: str) -> list[AgentLogEntry]:
    rows = db.query(AgentLog).filter(AgentLog.run_id == run_id).order_by(AgentLog.id.asc()).all()
    return [AgentLogEntry.model_validate(r, from_attributes=True) for r in rows]


def get_result(db: Session, run_id: str) -> AgentRunResult | None:
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
    if run is None:
        return None

    ids = run.selected_ids
    if ids is None:
        # **失敗したときこそ理由が要る。** 「記録されていません」だけでは、
        # 設定が足りないのか、探しても見つからなかったのかが分からない。
        return AgentRunResult(run_id=run_id, status=run.status, recorded=False, error=run.error)

    rows = {
        r.opportunity_id: r
        for r in db.query(Opportunity).filter(Opportunity.opportunity_id.in_(ids)).all()
    }
    # **順位を保つ。** DB の返す順ではなく selected_ids の順。
    selected = [
        OpportunitySummary.model_validate(rows[i], from_attributes=True) for i in ids if i in rows
    ]
    return AgentRunResult(
        run_id=run_id,
        status=run.status,
        recorded=True,
        selected=selected,
        shortfall_reason=run.shortfall_reason,
        # **失敗の理由を隠さない。** 設定不足なら直せる。
        error=run.error,
    )
