"""Agent State。

単発の LLM 呼び出しではなく、State を持って判断・ループするための入れ物。
DB の AgentRun に同期させることで、途中で落ちても進捗を追跡できる。
"""

from __future__ import annotations

from pydantic import BaseModel, Field

from ai.schemas import GoalAnalysisOutput, SearchDirection
from schemas.agent import AgentRunStatus, AgentStep


class AgentState(BaseModel):
    run_id: str
    user_id: str

    status: AgentRunStatus = AgentRunStatus.QUEUED
    current_step: AgentStep | None = None
    message: str | None = None
    progress: int = 0
    error: str | None = None

    goal_analysis: GoalAnalysisOutput | None = None
    search_directions: list[SearchDirection] = Field(default_factory=list)

    # 発見済み Opportunity（評価前も含む）の opportunity_id
    discovered_ids: list[str] = Field(default_factory=list)
    selected_ids: list[str] = Field(default_factory=list)

    # 探索の繰り返し回数。上限を超えたら打ち切る。
    iteration: int = 0
    max_iterations: int = 3

    cost_jpy: float = 0.0
    expensive_model_calls: int = 0

    @property
    def completed(self) -> bool:
        return self.status in (AgentRunStatus.COMPLETED, AgentRunStatus.FAILED)
