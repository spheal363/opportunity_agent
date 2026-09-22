"""AgentRun / AgentLog スキーマ。"""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field

from schemas.opportunity import OpportunitySummary, Timestamp


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


class AgentRunTrigger(StrEnum):
    """探索を始めたきっかけ（#84）。**manual 以外は Agent が自分で始めた。**

    自動にするのは発見だけ。Calendar への書き込みなど外部への操作は人のまま。
    判定と上限は services/auto_explore.py。
    """

    MANUAL = "manual"  # ボタン・目標の保存（POST /api/agent/runs）
    FEEDBACK = "feedback"  # 最新の推薦の過半数に👎が付いた
    STALE = "stale"  # 推薦中・保存中の機会が締切切れで減った
    SCHEDULED = "scheduled"  # 前回の探索から一定時間たった


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

    # 何がきっかけで始まったか。manual 以外は Agent が自分で始めた探索で、
    # trigger_reason に「なぜ始めたか」が入る。**決まった文面と数値だけ**で、
    # Web 由来の文は入らない。manual では null。
    trigger: AgentRunTrigger = AgentRunTrigger.MANUAL
    trigger_reason: str | None = None


class AgentRunHistoryEntry(AgentRunState):
    created_at: Timestamp = None
    selected_count: int | None = Field(default=None, ge=0)


class AgentRunHistory(BaseModel):
    items: list[AgentRunHistoryEntry] = Field(default_factory=list)
    next_cursor: str | None = None


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
