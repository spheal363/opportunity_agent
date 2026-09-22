"""探索の対象期間（#47）。固定日時だけで判定する。ネットワークへは出ない。"""

from datetime import UTC, date, datetime

import pytest

from ai import window as w

# 「今日」は 2026-09-22（JST）とし、期間は 60 日先の 2026-11-21 まで。
WINDOW = w.SearchWindow(start=date(2026, 9, 22), end=date(2026, 11, 21), timezone="Asia/Tokyo")


def _at(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=UTC)


def _classify(t, start=None, end=None, window=WINDOW):
    return w.classify(opportunity_type=t, start_at=start, end_at=end, window=window)


# --- 期間の確定 -----------------------------------------------------------


def test_the_window_is_60_days_by_default():
    win = w.for_now()
    assert win.days == w.DEFAULT_WINDOW_DAYS == 60


def test_the_window_uses_the_users_timezone():
    """UTC の今日だと、日本の朝 9 時前に走らせたとき前日から数える。"""
    jst = w.for_now(timezone="Asia/Tokyo")
    utc = w.for_now(timezone="UTC")
    assert (jst.start - utc.start).days in (0, 1)


def test_the_window_survives_a_round_trip():
    """run に保存して読み戻しても同じ期間。**途中で作り直さない。**"""
    assert w.SearchWindow.from_dict(WINDOW.to_dict()) == WINDOW


def test_a_broken_record_does_not_crash_the_run():
    """この列が付く前の run。**無いものとして扱う。**"""
    assert w.SearchWindow.from_dict(None) is None
    assert w.SearchWindow.from_dict({"start": "こわれた"}) is None


def test_an_unknown_timezone_falls_back_instead_of_failing():
    assert w.for_now(timezone="Mars/Olympus").timezone == w.DEFAULT_TIMEZONE


def test_the_window_length_is_bounded():
    assert w.for_now(days=1).days == w.MIN_WINDOW_DAYS
    assert w.for_now(days=10_000).days == w.MAX_WINDOW_DAYS


# --- 分類 -----------------------------------------------------------------


def test_an_event_inside_the_window():
    assert _classify("hackathon", _at(2026, 10, 10, 1)) is w.WindowStatus.IN_WINDOW


def test_an_event_after_the_window():
    """60 日より先。**期間内の候補には混ぜない。**"""
    assert _classify("hackathon", _at(2026, 12, 19)) is w.WindowStatus.AFTER_WINDOW


def test_an_event_that_already_ended():
    assert _classify("event", _at(2026, 8, 1)) is w.WindowStatus.ENDED


def test_a_multi_day_event_that_started_before_today_is_not_ended():
    """開始済みでも、終わっていなければ参加できる。**落とさない。**

    ただし「期間内に開催」とも言わない（始まったのは期間より前）。
    """
    status = _classify("event", _at(2026, 9, 20), _at(2026, 9, 25))
    assert status is not w.WindowStatus.ENDED
    assert status is w.WindowStatus.ONGOING


def test_an_event_without_a_date_is_not_guessed_into_the_window():
    """**推測で期間内に入れない。** 日程未確認として分ける。"""
    assert _classify("hackathon", None, None) is w.WindowStatus.SCHEDULE_UNKNOWN


@pytest.mark.parametrize("kind", ["community", "job", "freelance", "scholarship", "accelerator"])
def test_year_round_kinds_are_not_filtered_by_the_event_window(kind):
    """**通年募集にイベントの開催期間を当てない。**

    開催日が無いコミュニティを「期間外」にすると、毎月開催の勉強会が
    まるごと消える。
    """
    assert _classify(kind, None, None) is w.WindowStatus.NOT_TIME_BOUND
    # 日付があっても、期間の外だからという理由では落とさない。
    assert _classify(kind, _at(2027, 5, 1)) is w.WindowStatus.NOT_TIME_BOUND


# --- タイムゾーン ---------------------------------------------------------


def test_the_boundary_is_judged_in_the_users_timezone():
    """UTC で 11/21 15:00 は JST の 11/22。**期間の外。**

    UTC のまま比べると期間内に見える。
    """
    assert _classify("event", _at(2026, 11, 21, 15)) is w.WindowStatus.AFTER_WINDOW
    assert _classify("event", _at(2026, 11, 21, 14)) is w.WindowStatus.IN_WINDOW


def test_a_date_only_event_on_the_last_day_is_inside():
    """日付だけの情報。**時刻が無いことを理由に落とさない。**

    抽出は日付のみを JST 00:00 -> UTC 前日 15:00 で保存する。
    """
    assert _classify("event", _at(2026, 11, 20, 15)) is w.WindowStatus.IN_WINDOW


def test_a_naive_datetime_from_sqlite_is_treated_as_utc():
    """SQLite は tz を保持しない。naive を現地時間と誤解しない。"""
    naive = datetime(2026, 10, 10, 1)
    assert _classify("event", naive) is w.WindowStatus.IN_WINDOW


# --- 表示 -----------------------------------------------------------------


def test_every_status_has_a_label():
    """**対象種別と期間条件の関係を画面に出す。**"""
    for status in w.WindowStatus:
        assert w.label(status, WINDOW).strip()


def test_the_unknown_label_does_not_claim_a_date():
    assert "日程未確認" in w.label(w.WindowStatus.SCHEDULE_UNKNOWN, WINDOW)


def test_a_series_that_started_before_the_window_is_not_called_in_window():
    """**「期間内に開催」と言えない。**

    実測で、2026 年度の連続講座（4/1 開始・翌 1/30 終了）が
    「2026/09/22〜2026/11/21 に開催」と表示された。始まったのは期間より前。
    """
    status = _classify("event", _at(2026, 3, 31, 15), _at(2027, 1, 30, 15))
    assert status is w.WindowStatus.ONGOING
    assert "より前に開始" in w.label(status, WINDOW)


def test_the_not_time_bound_label_does_not_claim_year_round():
    """**種別だけで「通年」と断定しない。**

    開催期間で絞らないことと、通年募集であることは別。
    """
    assert "通年" not in w.label(w.WindowStatus.NOT_TIME_BOUND, WINDOW)
