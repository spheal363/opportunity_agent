"""Feedback スキーマ。Reflection / Agent Memory の入力になる。"""

from enum import StrEnum

from pydantic import BaseModel, Field


class Reaction(StrEnum):
    LIKE = "like"
    DISLIKE = "dislike"


class FeedbackCreate(BaseModel):
    reaction: Reaction
    attended: bool | None = None
    outcome_score: int | None = Field(default=None, ge=1, le=5)


class FeedbackResult(BaseModel):
    opportunity_id: str
    recorded: bool = True
