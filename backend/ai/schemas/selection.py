"""⑤ TOP3 Selection の入出力。"""

from pydantic import BaseModel, Field


class SelectionCandidate(BaseModel):
    opportunity_id: str
    score: int = Field(ge=0, le=100)
    serendipity_score: int = Field(ge=0, le=100)


class SelectionInput(BaseModel):
    opportunities: list[SelectionCandidate] = Field(default_factory=list)


class SelectionOutput(BaseModel):
    selected_opportunity_ids: list[str] = Field(default_factory=list)
