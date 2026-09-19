"""④ Opportunity Evaluation の入出力。"""

from pydantic import BaseModel, Field


class EvaluationInput(BaseModel):
    user_profile: dict
    opportunity: dict


class EvaluationOutput(BaseModel):
    score: int = Field(ge=0, le=100)
    serendipity_score: int = Field(ge=0, le=100)
    match_reasons: list[str] = Field(default_factory=list)
    concerns: list[str] = Field(default_factory=list)
    evaluation_summary: str | None = None
