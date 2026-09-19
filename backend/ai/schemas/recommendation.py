"""⑥ Recommendation Generation の入出力。"""

from pydantic import BaseModel, Field


class RecommendationInput(BaseModel):
    user_goals: list[str] = Field(default_factory=list)
    opportunity: dict
    evaluation: dict


class RecommendationOutput(BaseModel):
    reason: str
    highlights: list[str] = Field(default_factory=list)
