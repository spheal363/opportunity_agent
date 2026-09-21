"""Google Calendar 連携（#44 / #46）。

read（空き確認）は自動、write（予定追加）はユーザーのボタン操作を承認として実行する。
権限の定義は tools/calendar.py、Google との通信は tools/google_calendar.py。
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from models import Opportunity
from schemas.calendar import CalendarAvailability, CalendarConflict, CalendarEventCreated
from schemas.opportunity import OpportunityStatus
from tools import registry
from tools.google_calendar import CalendarError, EventDraft, InsertedEvent, event_id_for

# 終了時刻が取れていない機会は、この長さの予定として入れる。
# 推測した事実として見せないよう、予定の説明にも「仮」と書く。
# Frontend の確認表示もこれに合わせている（docs/api.md）。
PLACEHOLDER_DURATION = timedelta(hours=1)


class ScheduleUnknown(CalendarError):
    """開催日時が取れていないので、予定にできない。推測では埋めない。"""

    code = "SCHEDULE_UNKNOWN"


def check_availability(db: Session, opportunity_id: str) -> CalendarAvailability | None:
    row = db.get(Opportunity, opportunity_id)
    if row is None:
        return None
    start_at, end_at, _ = _window(row)
    result = registry.invoke(
        "check_calendar",
        start=start_at,
        end=end_at,
        # すでに入れた予定を「重なり」として数えない。
        ignore_event_id=event_id_for(row.opportunity_id),
    )
    # Google はカレンダーのタイムゾーンで返す。API の日時は UTC に揃える（docs/api.md）。
    conflicts = [
        CalendarConflict(
            title=b.title, start_at=b.start_at.astimezone(UTC), end_at=b.end_at.astimezone(UTC)
        )
        for b in result.data
    ]
    return CalendarAvailability(available=not conflicts, conflicts=conflicts)


def add_event(db: Session, opportunity_id: str) -> CalendarEventCreated | None:
    row = db.get(Opportunity, opportunity_id)
    if row is None:
        return None
    start_at, end_at, end_is_placeholder = _window(row)
    draft = EventDraft(
        event_id=event_id_for(row.opportunity_id),
        title=row.title,
        start_at=start_at,
        end_at=end_at,
        location=row.location,
        description=_description(row, end_is_placeholder),
    )
    # ここへ来るのは POST /opportunities/{id}/calendar、つまりユーザーが画面で
    # 追加内容を確認してボタンを押したときだけ。その操作を承認として扱う。
    # Agent Loop からは approved=True で呼ばない。
    inserted: InsertedEvent = registry.invoke("add_calendar_event", approved=True, event=draft).data

    # 予定に入れた = 参加するつもりがある。「次の一歩」に並べる。参加済みは戻さない。
    if row.status != OpportunityStatus.ATTENDED:
        row.status = OpportunityStatus.REGISTERED
        db.commit()
    return CalendarEventCreated(
        calendar_event_id=inserted.event_id,
        status="created" if inserted.created else "already_exists",
    )


def _window(row: Opportunity) -> tuple[datetime, datetime, bool]:
    """予定にする時間帯と、終了時刻が仮の値かどうか。"""
    if row.start_at is None:
        raise ScheduleUnknown("開催日時が分かっていないため、カレンダーで確認・追加できません")
    start_at = _as_utc(row.start_at)
    if row.end_at is not None and _as_utc(row.end_at) > start_at:
        return start_at, _as_utc(row.end_at), False
    return start_at, start_at + PLACEHOLDER_DURATION, True


def _as_utc(value: datetime) -> datetime:
    # SQLite は tz を保持しないため、naive な値は UTC とみなす（schemas/opportunity.py と同じ）。
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _description(row: Opportunity, end_is_placeholder: bool) -> str:
    lines: list[str] = []
    # Web から取った URL。javascript: などは載せない。
    if row.url and urlparse(row.url).scheme in ("http", "https"):
        lines.append(f"公式ページ: {row.url}")
    if end_is_placeholder:
        hours = int(PLACEHOLDER_DURATION.total_seconds() // 3600)
        lines.append(f"終了時刻は分かっていないため、仮に {hours} 時間で入れています。")
    lines.append(
        "Opportunity Agent から追加した予定です。日時や内容は公式ページで確認してください。"
    )
    return "\n".join(lines)
