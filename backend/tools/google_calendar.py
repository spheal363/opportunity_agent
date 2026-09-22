"""Google Calendar API の薄いクライアント（#43）。

認証は `scripts/google_auth.py` で最初に 1 回だけ行い、得たトークンを
`GOOGLE_TOKEN_PATH` に保存しておく。ここはそれを読んで API を呼ぶだけで、
ブラウザを開く処理は持たない。リクエストの途中で「許可」待ちにならないようにするため。

  - アクセストークン（約 1 時間）は、切れていれば呼び出し時に自動で取り直す
  - リフレッシュトークンは、テスト公開中のアプリだと 7 日で失効する。
    失効したら CalendarNotConnected にして、スクリプトの再実行を促す

トークンは Secret。ファイルの中身も、Google が返したエラーの本文も Log へ出さない。
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta, tzinfo
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import google_auth_httplib2
import httplib2
from google.auth.exceptions import GoogleAuthError, RefreshError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from config import Settings, get_settings
from logging_config import get_logger

logger = get_logger(__name__)

# 予定の読み取りと追加の両方ができる、いちばん狭いスコープ。
# カレンダー自体の作成・削除や共有設定の変更はできない。
SCOPES = ["https://www.googleapis.com/auth/calendar.events"]
CALENDAR_ID = "primary"
DEFAULT_TIMEOUT_SECONDS = 15.0
# 1 つの機会の時間帯に重なる予定の上限。これ以上は画面に並べても読まれない。
MAX_LISTED_EVENTS = 50

RECONNECT_HINT = "backend/ で `.venv/bin/python -m scripts.google_auth` を実行してください"


class CalendarError(Exception):
    """Calendar 連携の失敗。code は Frontend が表示を分けるのに使う。"""

    code = "CALENDAR_ERROR"

    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


class CalendarNotConnected(CalendarError):
    """トークンが無い・失効した・権限が足りない。スクリプトの再実行で直る。"""

    code = "CALENDAR_NOT_CONNECTED"


class _AlreadyExists(CalendarError):
    """同じ ID の予定がすでにある（HTTP 409）。insert_event の中だけで扱う。"""


@dataclass(frozen=True)
class BusyEvent:
    """時間帯が重なる既存の予定。"""

    title: str
    start_at: datetime
    end_at: datetime


@dataclass(frozen=True)
class EventDraft:
    """カレンダーへ入れる予定。中身は Web 上の事実だけで、AI の評価は入れない。"""

    event_id: str
    title: str
    start_at: datetime
    end_at: datetime
    location: str | None = None
    description: str | None = None
    # **出典に時刻が無かった。** 終日予定として入れる（#47）。
    # 時刻が無いものを 00:00 開始の予定にすると、こちらが決めた時刻を
    # 出典の値として見せることになる。
    all_day: bool = False
    # 終日予定を組み立てるタイムゾーン。日付は利用者の地域で決まる。
    timezone: str = "Asia/Tokyo"


@dataclass(frozen=True)
class InsertedEvent:
    event_id: str
    # False は「同じ予定がもう入っていた」。二重には入れない。
    created: bool


def event_id_for(opportunity_id: str) -> str:
    """Opportunity ごとに決まる Google 側の予定 ID。

    同じ ID の予定は 1 件しか作れないので、ボタンを 2 回押しても予定は増えない。
    DB に予定 ID を持たずに二重登録を防ぐためのもの。
    Google の ID は base32hex（0-9 a-v）の 5〜1024 文字なので、16 進の hash をそのまま使える。
    """
    digest = hashlib.sha256(opportunity_id.encode()).hexdigest()[:32]
    return f"oa{digest}"


def load_credentials(path: Path) -> Credentials:
    if not path.exists():
        raise CalendarNotConnected(f"Google Calendar と連携していません。{RECONNECT_HINT}")
    try:
        # scopes は渡さない。渡すとファイルに記録された権限が上書きされ、
        # 読み取り専用のトークン（記事のサンプルで作ったもの等）でも足りているように見える。
        creds = Credentials.from_authorized_user_file(str(path))
    except (ValueError, OSError) as exc:
        raise CalendarNotConnected(f"Google のトークンを読めません。{RECONNECT_HINT}") from exc
    if not creds.has_scopes(SCOPES):
        raise CalendarNotConnected(f"予定を追加する権限がありません。{RECONNECT_HINT}")
    return creds


class GoogleCalendarClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        service_factory: Callable[[], Any] | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._settings = settings or get_settings()
        self._timeout = timeout
        # テストでは Google の API を呼ばない偽物を渡す。
        self._service_factory = service_factory or self._build_service

    def _build_service(self) -> Any:
        # トークンは呼び出しごとに読む。スクリプトを再実行したら Backend の再起動なしで効く。
        creds = load_credentials(Path(self._settings.google_token_path))
        # httplib2 はスレッドセーフでないので呼び出しごとに作る（API は threadpool で並ぶ）。
        http = google_auth_httplib2.AuthorizedHttp(creds, http=httplib2.Http(timeout=self._timeout))
        # 同梱の API 定義を使い、起動時にネットワークへ取りに行かない。
        return build("calendar", "v3", http=http, static_discovery=True, cache_discovery=False)

    def list_busy(
        self, start: datetime, end: datetime, *, ignore_event_id: str | None = None
    ) -> list[BusyEvent]:
        """start〜end に重なり、時間を塞いでいる予定。"""
        service = self._service_factory()
        body = _execute(
            service.events().list(
                calendarId=CALENDAR_ID,
                timeMin=_rfc3339(start),
                timeMax=_rfc3339(end),
                # 繰り返しの予定を 1 回ずつに展開する
                singleEvents=True,
                orderBy="startTime",
                maxResults=MAX_LISTED_EVENTS,
            )
        )
        zone = _zone(body.get("timeZone"))
        items = body.get("items")
        busy: list[BusyEvent] = []
        for item in items if isinstance(items, list) else []:
            if not isinstance(item, dict) or not _blocks_time(item, ignore_event_id):
                continue
            start_at = _parse_when(item.get("start"), zone)
            end_at = _parse_when(item.get("end"), zone)
            if start_at is None or end_at is None:
                continue
            title = item.get("summary")
            busy.append(
                BusyEvent(
                    title=title if isinstance(title, str) and title else "（タイトルなし）",
                    start_at=start_at,
                    end_at=end_at,
                )
            )
        # 予定のタイトルは個人情報なので件数だけ残す。
        logger.info("calendar.list busy=%d", len(busy))
        return busy

    def insert_event(self, draft: EventDraft) -> InsertedEvent:
        service = self._service_factory()
        body = _event_body(draft)
        try:
            _execute(
                service.events().insert(calendarId=CALENDAR_ID, body={**body, "id": draft.event_id})
            )
        except _AlreadyExists:
            existing = _execute(
                service.events().get(calendarId=CALENDAR_ID, eventId=draft.event_id)
            )
            if existing.get("status") != "cancelled":
                logger.info("calendar.insert already_exists")
                return InsertedEvent(draft.event_id, created=False)
            # ユーザーがカレンダーから消した予定。消しても ID は残るので、同じ ID のまま戻す。
            _execute(
                service.events().update(
                    calendarId=CALENDAR_ID,
                    eventId=draft.event_id,
                    body={**body, "status": "confirmed"},
                )
            )
        logger.info("calendar.insert created")
        return InsertedEvent(draft.event_id, created=True)


def _execute(request: Any) -> dict[str, Any]:
    """API を呼び、失敗を CalendarError に寄せる。"""
    try:
        body = request.execute(num_retries=1)
    except HttpError as exc:
        status = exc.status_code
        # 本文には予定の中身が入りうるので、Log には status だけ出す。
        logger.warning("calendar.api_error status=%s", status)
        if status == 409:
            raise _AlreadyExists("同じ予定がすでにあります") from exc
        if status == 401:
            raise CalendarNotConnected(
                f"Google Calendar の認証が切れています。{RECONNECT_HINT}"
            ) from exc
        raise CalendarError(f"Google Calendar がエラーを返しました（HTTP {status}）") from exc
    except RefreshError as exc:
        # テスト公開中のアプリはリフレッシュトークンが 7 日で失効する。
        # アカウント側でアクセスを取り消されたときも、ここに来る（invalid_grant）。
        logger.warning("calendar.refresh_failed")
        raise CalendarNotConnected(
            f"Google Calendar との連携が切れました（期限切れか、許可の取り消し）。{RECONNECT_HINT}"
        ) from exc
    except (GoogleAuthError, httplib2.HttpLib2Error, OSError) as exc:
        # 例外の文言に URL やヘッダが入りうるので、型名だけ残す。
        logger.warning("calendar.transport_error type=%s", type(exc).__name__)
        raise CalendarError("Google Calendar に接続できませんでした") from exc
    if not isinstance(body, dict):
        raise CalendarError("Google Calendar の応答が想定と違います")
    return body


def _blocks_time(item: dict[str, Any], ignore_event_id: str | None) -> bool:
    """その予定が時間を塞いでいるか。"""
    if item.get("status") == "cancelled":
        return False
    # 「予定なし」として入れた予定（空き時間扱い）は塞がない。
    if item.get("transparency") == "transparent":
        return False
    # これから入れる予定そのもの。自分とは重ならない。
    if ignore_event_id and item.get("id") == ignore_event_id:
        return False
    # 辞退した招待。
    attendees = item.get("attendees")
    for attendee in attendees if isinstance(attendees, list) else []:
        if (
            isinstance(attendee, dict)
            and attendee.get("self")
            and attendee.get("responseStatus") == "declined"
        ):
            return False
    return True


def _parse_when(value: Any, zone: tzinfo) -> datetime | None:
    if not isinstance(value, dict):
        return None
    try:
        if value.get("dateTime"):
            parsed = datetime.fromisoformat(value["dateTime"])
            return parsed if parsed.tzinfo else parsed.replace(tzinfo=zone)
        if value.get("date"):
            # 終日の予定。そのカレンダーのタイムゾーンでの 0 時とする。
            return datetime.combine(date.fromisoformat(value["date"]), time(), tzinfo=zone)
    except (TypeError, ValueError):
        return None
    return None


def _zone(name: Any) -> tzinfo:
    if not isinstance(name, str) or not name:
        return UTC
    try:
        return ZoneInfo(name)
    except (ZoneInfoNotFoundError, ValueError):
        return UTC


def _rfc3339(value: datetime) -> str:
    # SQLite から来た naive な値は UTC とみなす（schemas/opportunity.py と同じ扱い）。
    return (value if value.tzinfo else value.replace(tzinfo=UTC)).isoformat()


def _event_body(draft: EventDraft) -> dict[str, Any]:
    if draft.all_day:
        # Google の終日予定は date で指定し、**end は翌日**（排他）。
        # 1 日だけの催しで end に同じ日を入れると API が弾く。
        tz = ZoneInfo(draft.timezone)
        start_date = draft.start_at.astimezone(tz).date()
        end_date = max(draft.end_at.astimezone(tz).date(), start_date)
        body: dict[str, Any] = {
            "summary": draft.title,
            "start": {"date": start_date.isoformat()},
            "end": {"date": (end_date + timedelta(days=1)).isoformat()},
        }
    else:
        body = {
            "summary": draft.title,
            "start": {"dateTime": _rfc3339(draft.start_at)},
            "end": {"dateTime": _rfc3339(draft.end_at)},
        }
    if draft.location:
        body["location"] = draft.location
    if draft.description:
        body["description"] = draft.description
    return body
