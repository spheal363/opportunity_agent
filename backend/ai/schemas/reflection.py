"""⑧ Reflection / Learning の入出力。結果は Agent Memory へ保存する。"""

from pydantic import BaseModel, Field


class ReflectionInput(BaseModel):
    opportunity: dict
    feedback: dict
    current_memory: list[dict] = Field(default_factory=list)


class PreferenceUpdate(BaseModel):
    key: str
    adjustment: float


class ReflectionOutput(BaseModel):
    insights: list[str] = Field(default_factory=list)
    preference_updates: list[PreferenceUpdate] = Field(default_factory=list)
    next_search_suggestions: list[str] = Field(default_factory=list)
