"""Feedback。Reflection の入力になる。"""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class Feedback(Base):
    __tablename__ = "feedbacks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    opportunity_id: Mapped[str] = mapped_column(String, index=True)

    reaction: Mapped[str] = mapped_column(String)
    attended: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    outcome_score: Mapped[int | None] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
