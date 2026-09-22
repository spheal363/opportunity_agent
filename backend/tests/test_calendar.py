"""Google Calendar 連携（#43 / #44 / #46）。Google の API は呼ばず、偽物の service で確かめる。"""

import json
from datetime import UTC, datetime

import httplib2
import pytest
from google.auth.exceptions import RefreshError
from googleapiclient.errors import HttpError

from api.deps import PAGE_REQUEST_HEADER_VALUE
from config import Settings
from db.session import SessionLocal
from models import Opportunity
from tools import calendar as calendar_tools
from tools.google_calendar import (
    SCOPES,
    CalendarError,
    CalendarNotConnected,
    GoogleCalendarClient,
    _execute,
    event_id_for,
    load_credentials,
)

START = datetime(2026, 10, 10, 10, 0, tzinfo=UTC)


# --- 偽物の Calendar API -----------------------------------------------------


class _Request:
    def __init__(self, fn):
        self._fn = fn

    def execute(self, num_retries: int = 0):
        return self._fn()


def _http_error(status: int) -> HttpError:
    return HttpError(httplib2.Response({"status": status}), b"{}")


class FakeService:
    """events().list / insert / get / update だけを持つ。"""

    def __init__(self, list_body: dict | None = None) -> None:
        self.list_body = list_body or {"items": []}
        self.store: dict[str, dict] = {}
        self.calls: list[tuple[str, dict]] = []

    def events(self):
        return self

    def list(self, **kwargs):
        self.calls.append(("list", kwargs))
        return _Request(lambda: self.list_body)

    def insert(self, calendarId, body):
        self.calls.append(("insert", body))

        def run():
            if body["id"] in self.store:
                raise _http_error(409)
            self.store[body["id"]] = body
            return body

        return _Request(run)

    def get(self, calendarId, eventId):
        self.calls.append(("get", {"eventId": eventId}))
        return _Request(lambda: self.store[eventId])

    def update(self, calendarId, eventId, body):
        self.calls.append(("update", body))

        def run():
            self.store[eventId] = {**body, "id": eventId}
            return self.store[eventId]

        return _Request(run)


@pytest.fixture
def service(monkeypatch) -> FakeService:
    fake = FakeService()
    client = GoogleCalendarClient(service_factory=lambda: fake)
    monkeypatch.setattr(calendar_tools, "get_client", lambda: client)
    return fake


def _seed(**overrides) -> str:
    values = {
        "opportunity_id": "opp_cal",
        "user_id": "user_001",
        "type": "event",
        "title": "AI Music Hackathon",
        "url": "https://example.com/event",
        "start_at": START,
        "location": "Tokyo",
        "status": "interested",
    }
    values.update(overrides)
    with SessionLocal() as s:
        s.add(Opportunity(**values))
        s.commit()
    return values["opportunity_id"]


def _status(opportunity_id: str) -> str:
    with SessionLocal() as s:
        return s.get(Opportunity, opportunity_id).status


# --- トークン -----------------------------------------------------------------


def _write_token(path, scopes):
    path.write_text(
        json.dumps(
            {
                "token": "access",
                "refresh_token": "refresh",
                "client_id": "cid",
                "client_secret": "secret",
                "scopes": scopes,
            }
        )
    )


def test_missing_token_means_not_connected(tmp_path):
    with pytest.raises(CalendarNotConnected):
        load_credentials(tmp_path / "missing.json")


def test_read_only_token_is_rejected(tmp_path):
    """記事のサンプルで作った読み取り専用のトークンでは、予定を追加できない。"""
    path = tmp_path / "token.json"
    _write_token(path, ["https://www.googleapis.com/auth/calendar.readonly"])
    with pytest.raises(CalendarNotConnected):
        load_credentials(path)


def test_token_with_events_scope_is_loaded(tmp_path):
    path = tmp_path / "token.json"
    _write_token(path, SCOPES)
    assert load_credentials(path).refresh_token == "refresh"


def test_broken_token_file_means_not_connected(tmp_path):
    path = tmp_path / "token.json"
    path.write_text("{not json")
    with pytest.raises(CalendarNotConnected):
        load_credentials(path)


# --- API エラーの変換 ---------------------------------------------------------


def _failing(exc: Exception) -> _Request:
    def run():
        raise exc

    return _Request(run)


@pytest.mark.parametrize(
    "exc,expected",
    [
        (_http_error(401), CalendarNotConnected),
        # テスト公開中のアプリは 7 日でリフレッシュトークンが失効する
        (RefreshError("invalid_grant"), CalendarNotConnected),
        (_http_error(500), CalendarError),
        (TimeoutError(), CalendarError),
    ],
)
def test_api_failures_become_calendar_errors(exc, expected):
    with pytest.raises(expected):
        _execute(_failing(exc))


# --- 空き確認（#44） ----------------------------------------------------------


def test_only_events_that_block_time_are_conflicts():
    own = event_id_for("opp_cal")
    fake = FakeService(
        {
            "timeZone": "Asia/Tokyo",
            "items": [
                {
                    "id": "a",
                    "summary": "定例",
                    "start": {"dateTime": "2026-10-10T19:00:00+09:00"},
                    "end": {"dateTime": "2026-10-10T20:00:00+09:00"},
                },
                {
                    "id": "b",
                    "summary": "予定なし扱い",
                    "transparency": "transparent",
                    "start": {"dateTime": "2026-10-10T19:00:00+09:00"},
                    "end": {"dateTime": "2026-10-10T20:00:00+09:00"},
                },
                {"id": "c", "status": "cancelled"},
                {
                    "id": "d",
                    "summary": "辞退した招待",
                    "attendees": [{"self": True, "responseStatus": "declined"}],
                    "start": {"dateTime": "2026-10-10T19:00:00+09:00"},
                    "end": {"dateTime": "2026-10-10T20:00:00+09:00"},
                },
                {
                    "id": own,
                    "summary": "AI Music Hackathon",
                    "start": {"dateTime": "2026-10-10T19:00:00+09:00"},
                    "end": {"dateTime": "2026-10-10T20:00:00+09:00"},
                },
                # 終日の予定。タイトルが無いこともある
                {"id": "e", "start": {"date": "2026-10-10"}, "end": {"date": "2026-10-11"}},
            ],
        }
    )
    client = GoogleCalendarClient(service_factory=lambda: fake)

    busy = client.list_busy(START, START, ignore_event_id=own)

    assert [b.title for b in busy] == ["定例", "（タイトルなし）"]
    assert busy[1].start_at.isoformat() == "2026-10-10T00:00:00+09:00"


def test_availability_uses_a_placeholder_hour_when_end_is_unknown(client, service):
    oid = _seed()
    service.list_body = {
        "items": [
            {
                "id": "a",
                "summary": "定例",
                "start": {"dateTime": "2026-10-10T19:30:00+09:00"},
                "end": {"dateTime": "2026-10-10T20:30:00+09:00"},
            }
        ]
    }

    res = client.get(f"/api/calendar/availability?opportunity_id={oid}")

    assert res.status_code == 200
    data = res.json()["data"]
    assert data["available"] is False
    # API の日時は UTC に揃える
    assert data["conflicts"] == [
        {"title": "定例", "start_at": "2026-10-10T10:30:00Z", "end_at": "2026-10-10T11:30:00Z"}
    ]
    _, params = service.calls[0]
    assert params["timeMin"] == "2026-10-10T10:00:00+00:00"
    assert params["timeMax"] == "2026-10-10T11:00:00+00:00"


def test_availability_is_free_when_nothing_overlaps(client, service):
    oid = _seed(end_at=datetime(2026, 10, 10, 18, 0, tzinfo=UTC))

    res = client.get(f"/api/calendar/availability?opportunity_id={oid}")

    assert res.json()["data"] == {"available": True, "conflicts": []}
    assert service.calls[0][1]["timeMax"] == "2026-10-10T18:00:00+00:00"


def test_unknown_start_is_not_guessed(client, service):
    oid = _seed(start_at=None)

    res = client.get(f"/api/calendar/availability?opportunity_id={oid}")

    assert res.status_code == 422
    assert res.json()["error"]["code"] == "SCHEDULE_UNKNOWN"
    assert service.calls == []


def test_availability_for_missing_opportunity_is_404(client, service):
    res = client.get("/api/calendar/availability?opportunity_id=nope")
    assert res.status_code == 404


def test_not_connected_is_reported_with_its_own_code(client, monkeypatch, tmp_path):
    oid = _seed()
    settings = Settings(google_token_path=str(tmp_path / "missing.json"))
    monkeypatch.setattr(calendar_tools, "get_client", lambda: GoogleCalendarClient(settings))

    res = client.get(f"/api/calendar/availability?opportunity_id={oid}")

    assert res.status_code == 503
    assert res.json()["error"]["code"] == "CALENDAR_NOT_CONNECTED"


# --- 予定追加（#46） ----------------------------------------------------------

# 画面（frontend/src/api/client.ts）が付けるヘッダー
PAGE = {"X-Requested-With": PAGE_REQUEST_HEADER_VALUE}


def test_add_event_creates_it_and_moves_to_next_steps(client, service):
    oid = _seed()

    res = client.post(f"/api/opportunities/{oid}/calendar", headers=PAGE)

    assert res.status_code == 200
    assert res.json()["data"] == {"calendar_event_id": event_id_for(oid), "status": "created"}
    body = service.store[event_id_for(oid)]
    assert body["summary"] == "AI Music Hackathon"
    assert body["location"] == "Tokyo"
    assert body["start"] == {"dateTime": "2026-10-10T10:00:00+00:00"}
    assert body["end"] == {"dateTime": "2026-10-10T11:00:00+00:00"}
    # 終了時刻は推測した事実として見せない
    assert "仮に 1 時間" in body["description"]
    assert "https://example.com/event" in body["description"]
    assert _status(oid) == "registered"


def test_pressing_twice_does_not_duplicate(client, service):
    oid = _seed()
    client.post(f"/api/opportunities/{oid}/calendar", headers=PAGE)

    res = client.post(f"/api/opportunities/{oid}/calendar", headers=PAGE)

    assert res.json()["data"]["status"] == "already_exists"
    assert len(service.store) == 1


def test_event_deleted_in_google_is_restored(client, service):
    oid = _seed()
    service.store[event_id_for(oid)] = {"id": event_id_for(oid), "status": "cancelled"}

    res = client.post(f"/api/opportunities/{oid}/calendar", headers=PAGE)

    assert res.json()["data"]["status"] == "created"
    assert service.store[event_id_for(oid)]["status"] == "confirmed"


def test_known_end_is_used_and_not_marked_as_placeholder(client, service):
    oid = _seed(end_at=datetime(2026, 10, 10, 18, 0, tzinfo=UTC))

    client.post(f"/api/opportunities/{oid}/calendar", headers=PAGE)

    body = service.store[event_id_for(oid)]
    assert body["end"] == {"dateTime": "2026-10-10T18:00:00+00:00"}
    assert "仮に" not in body["description"]


def test_non_http_url_is_not_written_to_the_event(client, service):
    oid = _seed(url="javascript:alert(1)")

    client.post(f"/api/opportunities/{oid}/calendar", headers=PAGE)

    assert "javascript:" not in service.store[event_id_for(oid)]["description"]


def test_attended_is_not_moved_back(client, service):
    oid = _seed(status="attended")

    client.post(f"/api/opportunities/{oid}/calendar", headers=PAGE)

    assert _status(oid) == "attended"


def test_failed_add_keeps_status(client, monkeypatch, tmp_path):
    oid = _seed()
    settings = Settings(google_token_path=str(tmp_path / "missing.json"))
    monkeypatch.setattr(calendar_tools, "get_client", lambda: GoogleCalendarClient(settings))

    res = client.post(f"/api/opportunities/{oid}/calendar", headers=PAGE)

    assert res.status_code == 503
    assert _status(oid) == "interested"


def test_add_for_missing_opportunity_is_404(client, service):
    assert client.post("/api/opportunities/nope/calendar", headers=PAGE).status_code == 404


@pytest.mark.parametrize("headers", [{}, {"X-Requested-With": "XMLHttpRequest"}])
def test_add_without_page_header_is_refused(client, service, headers):
    # 別サイトの form 送信はこのヘッダーを付けられない。ボタンを押していないので書き込まない。
    oid = _seed()

    res = client.post(f"/api/opportunities/{oid}/calendar", headers=headers)

    assert res.status_code == 403
    assert res.json()["error"]["code"] == "FORBIDDEN"
    assert service.store == {}
    assert _status(oid) == "interested"
