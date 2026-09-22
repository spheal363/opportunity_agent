"""Agent Run の作成・状態取得。"""

import uuid

from sqlalchemy.orm import Session

from models import DEFAULT_USER_ID, AgentLog, AgentRun
from schemas.agent import AgentLogEntry, AgentRunState, AgentRunStatus


def create_run(db: Session, user_id: str = DEFAULT_USER_ID) -> str:
    run_id = f"run_{uuid.uuid4().hex[:12]}"
    db.add(AgentRun(run_id=run_id, user_id=user_id, status=AgentRunStatus.QUEUED))
    db.commit()
    return run_id


def get_run(db: Session, run_id: str, user_id: str) -> AgentRunState | None:
    """その人の run だけを返す（#69）。他人の run は存在しないのと同じに扱う。"""
    row = db.get(AgentRun, run_id)
    if row is None or row.user_id != user_id:
        return None
    return AgentRunState.model_validate(row, from_attributes=True)


def list_logs(db: Session, run_id: str) -> list[AgentLogEntry]:
    """run の Log。**呼ぶ前に `get_run` で所有者を確かめること。**"""
    rows = db.query(AgentLog).filter(AgentLog.run_id == run_id).order_by(AgentLog.id.asc()).all()
    return [AgentLogEntry.model_validate(r, from_attributes=True) for r in rows]
