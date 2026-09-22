"""AgentRun / AgentLog スキーマ。"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from schemas.opportunity import OpportunitySummary


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
    cost_jpy: float = Field(default=0.0, ge=0)
    expensive_model_calls: int = Field(default=0, ge=0)


class AgentRunResult(BaseModel):
    """GET /api/agent/runs/{run_id}/result。**この run の最終選定。**

    `GET /api/opportunities`（保存一覧の母集合）とは別物。あちらは status で
    絞った最新の一覧で、こちらは**その run で選んだものを順位順**に返す。

    `recorded` が False なら「まだ結果が無い」。未完了と、完了したが 0 件は
    `status` と `selected` の組で区別する。
    """

    run_id: str
    status: AgentRunStatus
    # 結果が記録されているか。未完了・古い run では False
    recorded: bool = False
    # 順位順。**3 件に満たないことがある**
    selected: list[OpportunitySummary] = Field(default_factory=list)
    # 3 件に満たなかった理由
    shortfall_reason: str | None = None
    # **失敗した理由。** 「記録されていません」だけでは原因が分からない。
    # 設定不足（鍵が無いなど）と、探しても見つからなかったことは別。
    error: str | None = None


class AgentLogEntry(BaseModel):
    """GET /api/agent/runs/{run_id}/logs。"""

    step: AgentStep
    message: str
    created_at: datetime | None = None
