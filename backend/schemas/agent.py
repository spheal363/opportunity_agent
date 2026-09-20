"""AgentRun / AgentLog スキーマ。"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class AgentRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class AgentStep(StrEnum):
    ANALYZING_PROFILE = "analyzing_profile"
    PLANNING = "planning"
    SEARCHING = "searching"
    EVALUATING = "evaluating"
    VERIFYING = "verifying"
    COMPLETED = "completed"


class AgentRunCreated(BaseModel):
    run_id: str
    status: AgentRunStatus


class AgentRunState(BaseModel):
    """GET /api/agent/runs/{run_id}。Frontend の探索中画面がポーリングする。"""

    run_id: str
    status: AgentRunStatus
    current_step: AgentStep | None = None
    message: str | None = None
    progress: int = Field(default=0, ge=0, le=100)
    error: str | None = None

    # この探索にかかった見積もり額と、高性能モデルを使った回数。
    # **見積もりであって請求額ではない**（ai/cost.py の単価表を参照）。
    # 「全件を高性能モデルへ投げていない」ことを示すために出す。
    cost_jpy: float = 0.0
    expensive_model_calls: int = 0


class AgentLogEntry(BaseModel):
    """GET /api/agent/runs/{run_id}/logs。"""

    step: AgentStep
    message: str
    created_at: datetime | None = None
