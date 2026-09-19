"""① Goal Analysis の入出力。"""

from pydantic import BaseModel, Field


class GoalAnalysisInput(BaseModel):
    occupation: str | None = None
    skills: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    about: str | None = None


class GoalAnalysisOutput(BaseModel):
    goal_summary: str
    goal_directions: list[str] = Field(default_factory=list)
    # 「AI × Music」のように複数の興味の交差点。Serendipity 探索の種になる。
    interest_connections: list[str] = Field(default_factory=list)
