"""Google Calendar 連携。

TODO(calendar): Google Calendar API を接続する。
read は自動、write はユーザー承認後にのみ実行する（tools/calendar.py の権限定義を使う）。
"""

from sqlalchemy.orm import Session

from schemas.calendar import CalendarAvailability, CalendarEventCreated


def check_availability(db: Session, opportunity_id: str) -> CalendarAvailability:
    raise NotImplementedError("calendar integration is not implemented yet")


def add_event(db: Session, opportunity_id: str) -> CalendarEventCreated:
    raise NotImplementedError("calendar integration is not implemented yet")
