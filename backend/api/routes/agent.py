from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from agent.loop import run_agent
from api.deps import current_user_id
from api.errors import NotFound
from db.session import get_db
from schemas.agent import AgentLogEntry, AgentRunCreated, AgentRunState, AgentRunStatus
from schemas.common import ApiSuccess, ok
from services import agent_service, profile_service

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post("/runs", response_model=ApiSuccess[AgentRunCreated])
def start_run(
    background: BackgroundTasks,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user_id),
) -> dict:
    """保存されている UserProfile をもとに Agent の探索を開始する。

    実行は非同期。Frontend は run_id を保持して状態をポーリングする。
    """
    if profile_service.get_profile(db, user_id) is None:
        raise NotFound("プロフィールが登録されていません")

    run_id = agent_service.create_run(db, user_id)
    background.add_task(run_agent, run_id, user_id)
    return ok(AgentRunCreated(run_id=run_id, status=AgentRunStatus.QUEUED))


@router.get("/runs/{run_id}", response_model=ApiSuccess[AgentRunState])
def get_run(run_id: str, db: Session = Depends(get_db)) -> dict:
    run = agent_service.get_run(db, run_id)
    if run is None:
        raise NotFound("指定された run_id が見つかりません")
    return ok(run)


@router.get("/runs/{run_id}/logs", response_model=ApiSuccess[list[AgentLogEntry]])
def get_run_logs(run_id: str, db: Session = Depends(get_db)) -> dict:
    if agent_service.get_run(db, run_id) is None:
        raise NotFound("指定された run_id が見つかりません")
    return ok(agent_service.list_logs(db, run_id))
