"""詳細確認（#47）。**外部 API を呼ばない。** 取得と抽出は差し替える。"""

from datetime import UTC, datetime, timedelta

import pytest

from db.session import SessionLocal
from models import DEFAULT_USER_ID
from models.opportunity import Opportunity
from services import detail_service
from tools.base import ToolResult


class _Page:
    def __init__(self, content: str) -> None:
        self.url = "https://example.test/a"
        self.title = "催しのページ"
        self.content = content


class _Extracted:
    """`extract_opportunity` の戻りのうち、ここで使う項目だけ。"""

    def __init__(self, **kw):
        self.start_at = kw.get("start_at")
        self.end_at = kw.get("end_at")
        self.start_at_is_date_only = True
        self.end_at_is_date_only = None
        self.location = kw.get("location")
        self.region = kw.get("region")
        self.format = None
        self.online_participation = None
        self.deadline = None
        self.eligibility = kw.get("eligibility")
        self.cost = None
        self.url = kw.get("url")


@pytest.fixture
def row():
    db = SessionLocal()
    o = Opportunity(
        opportunity_id="opp_test1",
        user_id=DEFAULT_USER_ID,
        type="event",
        title="テスト催し",
        url="https://example.test/a",
        start_at=datetime(2026, 11, 13, tzinfo=UTC),
        location="旧会場",
        wish="音楽",
        wish_source="四つ打ちの音楽を楽しみたい",
        searched_values={"dates": ["2026-11-13"], "venue": "旧会場"},
        corrections=[],
        confirmed_fields=[],
        evaluated=False,
    )
    db.add(o)
    db.commit()
    yield o.opportunity_id
    db.close()


def _patch(monkeypatch, extracted):
    monkeypatch.setattr(
        detail_service.registry,
        "invoke",
        lambda name, **kw: ToolResult({"pages": [_Page("本文")]}, external=True),
    )
    monkeypatch.setattr(detail_service.interstitial, "looks_like_interstitial", lambda **kw: None)
    monkeypatch.setattr(detail_service.extraction, "extract_opportunity", lambda *a, **k: extracted)


def test_訂正は履歴に積まれ検索時の値も残る(monkeypatch, row):
    _patch(monkeypatch, _Extracted(start_at=datetime(2026, 11, 14, tzinfo=UTC), location="WOMB"))
    db = SessionLocal()
    out = detail_service.check_detail(db, row, DEFAULT_USER_ID)
    assert out.start_at.date().isoformat() == "2026-11-14"
    fields = [c["field"] for c in out.corrections]
    assert "start_at" in fields and "location" in fields
    start = next(c for c in out.corrections if c["field"] == "start_at")
    assert start["before"] == "2026-11-13" and start["after"] == "2026-11-14"
    assert start["checked_at"] and start["source"] == "https://example.test/a"
    # **検索時の元データは消さない。**
    assert out.searched_values["dates"] == ["2026-11-13"]
    db.close()


def test_確認できた項目だけをconfirmed_fieldsに入れる(monkeypatch, row):
    _patch(monkeypatch, _Extracted(start_at=datetime(2026, 11, 14, tzinfo=UTC)))
    db = SessionLocal()
    out = detail_service.check_detail(db, row, DEFAULT_USER_ID)
    assert out.verified is True
    assert "start_at" in out.confirmed_fields
    # 会場も受付も抽出できていない -> **確認済みにしない**
    assert "location" not in out.confirmed_fields
    assert "deadline" not in out.confirmed_fields
    assert "application_url_on_page" not in out.confirmed_fields
    assert "eligibility_stated" not in out.confirmed_fields
    db.close()


def test_参加資格は記載の確認であって本人との照合ではない(monkeypatch, row):
    _patch(monkeypatch, _Extracted(eligibility="20歳以上"))
    db = SessionLocal()
    out = detail_service.check_detail(db, row, DEFAULT_USER_ID)
    assert "eligibility_stated" in out.confirmed_fields
    assert "eligibility_matched" not in out.confirmed_fields
    db.close()


def test_連打しても二重に走らない(monkeypatch, row):
    calls = {"n": 0}

    def _count(*a, **k):
        calls["n"] += 1
        return _Extracted(start_at=datetime(2026, 11, 14, tzinfo=UTC))

    _patch(monkeypatch, None)
    monkeypatch.setattr(detail_service.extraction, "extract_opportunity", _count)
    db = SessionLocal()
    detail_service.check_detail(db, row, DEFAULT_USER_ID)
    detail_service.check_detail(db, row, DEFAULT_USER_ID)
    detail_service.check_detail(db, row, DEFAULT_USER_ID)
    assert calls["n"] == 1  # **2 回目以降は取り直さない**
    db.close()


def test_取得できないときは誤りにせず未確認のまま(monkeypatch, row):
    monkeypatch.setattr(
        detail_service.registry,
        "invoke",
        lambda name, **kw: ToolResult({"pages": []}, external=True),
    )
    db = SessionLocal()
    out = detail_service.check_detail(db, row, DEFAULT_USER_ID)
    assert out.verified is False  # **確認済みにしない**
    assert out.confirmed_fields == []
    assert "取得できませんでした" in (out.availability_reason or "")
    assert out.corrections == []  # 誤りとして記録しない
    db.close()


def test_他人の候補は見えない(monkeypatch, row):
    _patch(monkeypatch, _Extracted())
    db = SessionLocal()
    assert detail_service.check_detail(db, row, "user_other") is None
    db.close()


def test_期限切れなら再確認する(monkeypatch, row):
    _patch(monkeypatch, _Extracted(start_at=datetime(2026, 11, 14, tzinfo=UTC)))
    db = SessionLocal()
    out = detail_service.check_detail(db, row, DEFAULT_USER_ID)
    out.detail_checked_at = datetime.now(UTC) - timedelta(
        seconds=detail_service.RECHECK_AFTER_SECONDS + 10
    )
    db.commit()
    assert detail_service._fresh(out) is False
    db.close()


def test_申込先は本文に実在するURLのときだけ印を付ける(monkeypatch, row):
    """**別URLというだけでは「申込先を確認した」と言えない。**"""
    _patch(monkeypatch, _Extracted(url="https://ticket.test/buy"))
    db = SessionLocal()
    out = detail_service.check_detail(db, row, DEFAULT_USER_ID)
    # 本文（"本文"）にその URL は無い -> 印を付けない
    assert "application_url_on_page" not in out.confirmed_fields
    assert out.application_url is None
    # **申込先として確かめていないので、情報源のままにする**
    assert out.url_is_source_only is True
    db.close()


def test_本文にあるURLなら実在だけを記録する(monkeypatch, row):
    monkeypatch.setattr(
        detail_service.registry,
        "invoke",
        lambda name, **kw: ToolResult(
            {"pages": [_Page("申込は https://ticket.test/buy から")]}, external=True
        ),
    )
    monkeypatch.setattr(detail_service.interstitial, "looks_like_interstitial", lambda **kw: None)
    monkeypatch.setattr(
        detail_service.extraction,
        "extract_opportunity",
        lambda *a, **k: _Extracted(url="https://ticket.test/buy"),
    )
    db = SessionLocal()
    out = detail_service.check_detail(db, row, DEFAULT_USER_ID)
    assert "application_url_on_page" in out.confirmed_fields
    assert out.application_url == "https://ticket.test/buy"
    # **「出典ページに実在する」までで、申込先だとは確認していない**
    assert out.url_is_source_only is True
    db.close()


def test_詳細確認の使用量を別に残す(monkeypatch, row):
    _patch(monkeypatch, _Extracted(start_at=datetime(2026, 11, 14, tzinfo=UTC)))
    db = SessionLocal()
    out = detail_service.check_detail(db, row, DEFAULT_USER_ID)
    assert out.detail_usage is not None
    assert out.detail_usage["page_fetches"] == 1
    assert "$0" in out.detail_usage["page_fetch_service"]
    db.close()


def test_日付は現地時刻で比べる(monkeypatch, row):
    """**UTC のまま `.date()` を取ると前日に見える。**

    JST 11/14 00:00 は UTC では 11/13 15:00。同じ日なのに
    「11/14 -> 11/13 に訂正」と出ていた（ブラウザで確認して判明）。
    """
    from zoneinfo import ZoneInfo

    jst = ZoneInfo("Asia/Tokyo")
    db = SessionLocal()
    o = db.get(Opportunity, row)
    o.start_at = datetime(2026, 11, 14, tzinfo=jst)  # JST の 11/14
    db.commit()
    # 出典も同じ 11/14（UTC 表現では 11/13 15:00）
    _patch(monkeypatch, _Extracted(start_at=datetime(2026, 11, 13, 15, 0, tzinfo=UTC)))
    out = detail_service.check_detail(db, row, DEFAULT_USER_ID)
    assert [c["field"] for c in out.corrections] == []  # **訂正は出ない**
    db.close()


def test_列を足す前の行もAPIの形にできる():
    """`ALTER TABLE` で足した列は、既存行では NULL になる（実機で 500 になった）。"""
    from schemas.opportunity import OpportunitySummary

    db = SessionLocal()
    o = Opportunity(
        opportunity_id="opp_old",
        user_id=DEFAULT_USER_ID,
        type="event",
        title="列を足す前からある行",
        corrections=None,
        confirmed_fields=None,
        match_reasons=None,
    )
    db.add(o)
    db.commit()
    out = OpportunitySummary.model_validate(o, from_attributes=True)
    assert out.corrections == [] and out.confirmed_fields == [] and out.match_reasons == []
    db.close()
