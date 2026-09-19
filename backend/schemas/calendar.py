"""Calendar 連携スキーマ。"""

from pydantic import BaseModel, Field

from schemas.opportunity import Timestamp


class CalendarConflict(BaseModel):
    title: str
    start_at: Timestamp
    end_at: Timestamp


class CalendarAvailability(BaseModel):
    available: bool
    conflicts: list[CalendarConflict] = Field(default_factory=list)


class CalendarEventCreated(BaseModel):
    calendar_event_id: str
    status: str = "created"
