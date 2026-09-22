"""Google Calendar 連携（#44 / #46）。

read（空き確認）は自動、write（予定追加）はユーザーのボタン操作を承認として実行する。
権限の定義は tools/calendar.py、Google との通信は tools/google_calendar.py。
"""

from datetime import UTC, datetime, timedelta
from urllib.parse import urlparse

from sqlalchemy.orm import Session

from models import Opportunity
from schemas.calendar import (
    CalendarAvailability,
    CalendarConflict,
    CalendarEventCreated,
    CalendarEventPreview,
)
from schemas.opportunity import OpportunityStatus
from services.opportunity_service import get_owned
from tools import registry
from tools.google_calendar import CalendarError, EventDraft, InsertedEvent, event_id_for

# 終了時刻が取れていない機会は、この長さの予定として入れる。
# 推測した事実として見せないよう、予定の説明にも「仮」と書く。
# Frontend の確認表示もこれに合わせている（docs/api.md）。
PLACEHOLDER_DURATION = timedelta(hours=1)

# 終日予定を組み立てる基準のタイムゾーン。画面の確認にもそのまま出す。
EVENT_TIMEZONE = "Asia/Tokyo"


class ScheduleUnknown(CalendarError):
    """開催日時が取れていないので、予定にできない。推測では埋めない。"""

    code = "SCHEDULE_UNKNOWN"


def check_availability(
    db: Session, opportunity_id: str, user_id: str
) -> CalendarAvailability | None:
    row = get_owned(db, opportunity_id, user_id)
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
    return CalendarAvailability(
        available=not conflicts,
        conflicts=conflicts,
        # **確認に出すのは、実際に送る内容そのもの。**
        event=_preview(row),
    )


def preview(db: Session, opportunity_id: str, user_id: str) -> CalendarEventPreview | None:
    """登録する内容だけを返す。カレンダーへは触らない。"""
    row = get_owned(db, opportunity_id, user_id)
    return None if row is None else _preview(row)


def _preview(row: Opportunity) -> CalendarEventPreview:
    start_at, end_at, end_is_placeholder = _window(row)
    all_day = row.start_at_is_date_only is True
    return CalendarEventPreview(
        title=row.title,
        start_at=start_at,
        end_at=end_at,
        all_day=all_day,
        timezone=EVENT_TIMEZONE,
        end_is_placeholder=end_is_placeholder and not all_day,
        location=row.location,
        source_url=_safe_url(row.url),
    )


def _safe_url(url: str | None) -> str | None:
    return url if url and urlparse(url).scheme in ("http", "https") else None


def add_event(db: Session, opportunity_id: str, user_id: str) -> CalendarEventCreated | None:
    row = get_owned(db, opportunity_id, user_id)
    if row is None:
        return None
    start_at, end_at, end_is_placeholder = _window(row)
    # **出典に時刻が無かったものは終日予定にする（#47）。**
    # 00:00 開始の 1 時間の予定にすると、こちらが決めた時刻を出典の値として
    # 見せることになる。`None`（時刻の有無が不明）も終日にはしない。
    all_day = row.start_at_is_date_only is True
    draft = EventDraft(
        event_id=event_id_for(row.opportunity_id),
        title=row.title,
        start_at=start_at,
        end_at=end_at,
        location=row.location,
        description=_description(row, end_is_placeholder and not all_day),
        all_day=all_day,
        timezone=EVENT_TIMEZONE,
    )
    # ここへ来るのは POST /opportunities/{id}/calendar、つまりユーザーが画面で
    # 追加内容を確認してボタンを押したときだけ。その操作を承認として扱う。
    # 画面以外（別サイトの form など）からの要求は route で止める（api/deps.py）。
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
    if _safe_url(row.url):
        lines.append(f"公式ページ: {row.url}")
    if row.start_at_is_date_only is True:
        lines.append("開始時刻が分かっていないため、終日の予定として入れています。")
    elif end_is_placeholder:
        hours = int(PLACEHOLDER_DURATION.total_seconds() // 3600)
        lines.append(f"終了時刻は分かっていないため、仮に {hours} 時間で入れています。")
    lines.append(
        "Opportunity Agent から追加した予定です。**この予定の追加は参加申込ではありません。**"
        "日時や内容は公式ページで確認し、申込はご自身で行ってください。"
    )
    return "\n".join(lines)
