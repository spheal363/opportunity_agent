"""② Search Planning の入出力。"""

from pydantic import BaseModel, Field

from schemas.opportunity import OpportunityType


class SearchPlanInput(BaseModel):
    goal_summary: str
    goal_directions: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)


class SearchDirection(BaseModel):
    category: OpportunityType
    query: str
    reason: str
    # Serendipity 狙いの探索方向かどうか。Search Plan には最低 1 つ含める。
    serendipity: bool = False


class SearchPlanOutput(BaseModel):
    search_directions: list[SearchDirection] = Field(default_factory=list)
