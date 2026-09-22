from fastapi import APIRouter, BackgroundTasks, Depends
from sqlalchemy.orm import Session

from agent.loop import run_agent
from api.deps import current_user_id, require_page_request
from api.errors import NotFound
from db.session import get_db
from schemas.agent import (
    AgentLogEntry,
    AgentRunCreated,
    AgentRunResult,
    AgentRunState,
    AgentRunStatus,
)
from schemas.common import ApiSuccess, ok
from services import agent_service, profile_service

router = APIRouter(prefix="/agent", tags=["agent"])


@router.post(
    "/runs",
    response_model=ApiSuccess[AgentRunCreated],
    # LLM の費用が発生する。別サイトから勝手に走らせない（#80）
    dependencies=[Depends(require_page_request)],
)
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


# **`/runs/{run_id}` より前に定義する。** 後ろに置くと "latest" が run_id として
# 解釈され、404（指定された run_id が見つかりません）になる。
@router.get("/runs/latest", response_model=ApiSuccess[AgentRunState | None])
def get_latest_run(
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user_id),
) -> dict:
    """現在のユーザーの最新 run（状態は問わない）。

    Agent が自分で始めた探索（`trigger` が manual 以外）をホームや👎の後に
    見つけるのに使う（#86）。**run が 1 件も無いときは 404 ではなく `data: null`。**
    まだ探索していないのは正常な状態で、画面が定期的に取りに来るため。
    """
    return ok(agent_service.get_latest_run(db, user_id))


@router.get("/runs/{run_id}", response_model=ApiSuccess[AgentRunState])
def get_run(
    run_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user_id),
) -> dict:
    run = agent_service.get_run(db, run_id, user_id)
    if run is None:
        raise NotFound("指定された run_id が見つかりません")
    return ok(run)


@router.get("/runs/{run_id}/logs", response_model=ApiSuccess[list[AgentLogEntry]])
def get_run_logs(
    run_id: str,
    db: Session = Depends(get_db),
    user_id: str = Depends(current_user_id),
) -> dict:
    if agent_service.get_run(db, run_id, user_id) is None:
        raise NotFound("指定された run_id が見つかりません")
    return ok(agent_service.list_logs(db, run_id))


@router.get("/runs/{run_id}/result", response_model=ApiSuccess[AgentRunResult])
def get_run_result(run_id: str, db: Session = Depends(get_db)) -> dict:
    """この run の最終選定。**結果画面はこれを使う。**

    `GET /api/opportunities` は保存一覧の母集合で、今回の選定とは別物。
    """
    result = agent_service.get_result(db, run_id)
    if result is None:
        raise NotFound("run が見つかりません")
    return ok(result)
