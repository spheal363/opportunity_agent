"""受付状況の判定（#68）。

**`verified`（情報を確認できたか）とは別の軸。** 確認できたうえで受付終了、
ということがある。
"""

from datetime import UTC, datetime, timedelta

import pytest

from ai.availability import Availability, as_utc, from_dates, is_actionable

NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)
PAST = NOW - timedelta(days=1)
FUTURE = NOW + timedelta(days=1)


# --- closed と言い切れるものだけ closed -----------------------------------


def test_past_deadline_is_closed():
    status, reason = from_dates(opportunity_type="hackathon", deadline=PAST, end_at=None, now=NOW)
    assert status is Availability.CLOSED
    assert "締切" in reason


def test_future_deadline_is_not_open():
    """**締切が未来というだけで受付中とは限らない。** 満員かもしれない。"""
    status, reason = from_dates(opportunity_type="hackathon", deadline=FUTURE, end_at=None, now=NOW)
    assert status is Availability.UNKNOWN
    assert reason is None


def test_null_deadline_is_unknown():
    """**受付終了でも受付中でもない。**"""
    status, _ = from_dates(opportunity_type="hackathon", deadline=None, end_at=None, now=NOW)
    assert status is Availability.UNKNOWN


# --- 種類ごとの扱い -------------------------------------------------------


@pytest.mark.parametrize(
    "opportunity_type,expected",
    [
        ("hackathon", Availability.CLOSED),
        ("event", Availability.CLOSED),
        ("competition", Availability.CLOSED),
        # 開催が終わるという概念が無いもの。終了日が過去でも閉じない
        ("community", Availability.UNKNOWN),
        ("job", Availability.UNKNOWN),
        ("freelance", Availability.UNKNOWN),
        ("other", Availability.UNKNOWN),
        (None, Availability.UNKNOWN),
        ("知らない種類", Availability.UNKNOWN),
    ],
)
def test_past_end_at_depends_on_the_type(opportunity_type, expected):
    status, _ = from_dates(opportunity_type=opportunity_type, deadline=None, end_at=PAST, now=NOW)
    assert status is expected


def test_deadline_takes_precedence_over_end_at():
    status, reason = from_dates(opportunity_type="community", deadline=PAST, end_at=FUTURE, now=NOW)
    assert status is Availability.CLOSED
    assert "締切" in reason


# --- SQLite の naive 日時 --------------------------------------------------


def test_naive_is_treated_as_utc():
    """**SQLite は tz を保持しない。** 読み出した値に UTC を付ける。"""
    assert as_utc(PAST.replace(tzinfo=None)) == PAST
    assert as_utc(None) is None
    assert as_utc(PAST) == PAST  # 既に付いていれば触らない


def test_naive_deadline_does_not_crash():
    status, _ = from_dates(
        opportunity_type="hackathon", deadline=PAST.replace(tzinfo=None), end_at=None, now=NOW
    )
    assert status is Availability.CLOSED


# --- 境界 -----------------------------------------------------------------


def test_exactly_now_is_not_closed():
    """同時刻は過ぎていない。"""
    status, _ = from_dates(opportunity_type="hackathon", deadline=NOW, end_at=None, now=NOW)
    assert status is Availability.UNKNOWN


# --- 行動できる推薦に混ぜてよいか -----------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        (Availability.OPEN, True),
        (Availability.UNKNOWN, True),  # **確認できていないだけ。終わったとは限らない**
        (Availability.CLOSED, False),
        (None, True),
    ],
)
def test_is_actionable(value, expected):
    assert is_actionable(value) is expected
