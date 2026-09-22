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
    # 希望した活動地域（#47）。プロフィールの値を run 開始時に写す。
    wanted_region: str | None = None
    # この run が対象にする期間（#47）。**run 開始時に確定し、途中で変えない。**
    search_window: dict | None = None
    discovered_ids: list[str] = Field(default_factory=list)
    # 評価で順位付けした全候補（上位から）。検証と繰り上げはここから取る。
    ranked_ids: list[str] = Field(default_factory=list)
    # 最終的に推薦する候補。**3 件に満たないことがある。**
    selected_ids: list[str] = Field(default_factory=list)
    # 3 件に満たなかった理由。run に保存して後からも同じ内容を返す。
    shortfall_reason: str | None = None
    # 行動の対象を特定できずに外した件数。**不足理由の説明に使う。**
    no_action_count: int = 0

    # 指示らしき文が見つかったページの URL（ai/guard.py, #27）と、
    # そこから取った Opportunity の id。推薦しない（#77）。
    flagged_urls: set[str] = Field(default_factory=set)
    flagged_ids: set[str] = Field(default_factory=set)

    # 探索の繰り返し回数。上限を超えたら打ち切る。
    iteration: int = 0
    max_iterations: int = 3

    cost_jpy: float = 0.0
    expensive_model_calls: int = 0

    @property
    def completed(self) -> bool:
        return self.status in (AgentRunStatus.COMPLETED, AgentRunStatus.FAILED)
