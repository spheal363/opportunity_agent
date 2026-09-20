"""③ Opportunity Extraction のテスト。

LLM も検索 API も叩かない。generate_structured を差し替える。
"""

from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from ai import extraction
from ai.llm import LLMResult, LLMValidationError
from ai.orcarouter import ModelTier
from ai.prompts import extraction as prompt
from ai.schemas.extraction import MAX_PAGE_CONTENT_CHARS, ExtractedOpportunity
from tools.search.base import PageContent, SearchResult


def _extracted(**overrides) -> ExtractedOpportunity:
    base = {"title": "AI Hackathon", "type": "hackathon"}
    base.update(overrides)
    return ExtractedOpportunity(**base)


def _Result(data: ExtractedOpportunity) -> LLMResult[ExtractedOpportunity]:
    """generate_structured の戻り値。

    ダブルを自作せず実物の LLMResult を使う。自作すると属性名がずれても
    テストが通ってしまう（実際に .value と書いて実 LLM で落とした）。
    """
    return LLMResult(data=data)


# --- スキーマ: タイムゾーン ------------------------------------------------


def test_naive_datetime_is_rejected():
    """naive な日時を UTC として保存すると 9 時間ずれる。弾く。"""
    with pytest.raises(ValidationError, match="タイムゾーン"):
        _extracted(start_at="2026-09-21T19:00:00")


def test_aware_datetime_is_accepted():
    o = _extracted(start_at="2026-09-21T19:00:00+09:00")
    assert o.start_at.utcoffset().total_seconds() == 9 * 3600


def test_null_datetime_is_allowed():
    """判断できない日時は null。ずれた値より無い方がよい。"""
    assert _extracted().start_at is None


def test_to_utc_normalizes():
    o = _extracted(
        start_at="2026-09-21T19:00:00+09:00",
        end_at="2026-09-22T18:00:00+09:00",
        deadline="2026-09-16T23:59:00+09:00",
    ).to_utc()

    assert o.start_at == datetime(2026, 9, 21, 10, 0, tzinfo=UTC)
    assert o.end_at == datetime(2026, 9, 22, 9, 0, tzinfo=UTC)
    assert o.deadline == datetime(2026, 9, 16, 14, 59, tzinfo=UTC)


def test_to_utc_keeps_null():
    assert _extracted().to_utc().start_at is None


# --- スキーマ: cost -------------------------------------------------------


def test_cost_zero_and_null_are_distinct():
    """無料は 0、不明は null。混同しない。"""
    assert _extracted(cost=0).cost == 0
    assert _extracted().cost is None


def test_negative_cost_is_rejected():
    with pytest.raises(ValidationError):
        _extracted(cost=-1)


# --- Prompt ---------------------------------------------------------------


def test_system_prompt_carries_untrusted_rule():
    assert "従ってはならない" in prompt.SYSTEM


def test_system_prompt_forbids_guessing():
    assert "推測せず null" in prompt.SYSTEM


def test_user_prompt_wraps_content_as_untrusted():
    user = prompt.build_user("https://e.com", "本文", today=date(2026, 9, 20))

    assert "<page_content>" in user
    assert "指示ではない" in user
    # 年の無い日付を解釈させるため今日の日付を渡す
    assert "2026-09-20" in user
    assert "https://e.com" in user


# --- extract_opportunity --------------------------------------------------


def test_extract_uses_standard_tier(monkeypatch):
    """Untrusted Data を読ませるため CHEAP は使わない。"""
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return _Result(_extracted())

    monkeypatch.setattr(extraction, "generate_structured", fake)
    extraction.extract_opportunity("https://e.com", "本文")

    assert seen["tier"] is ModelTier.STANDARD
    assert seen["schema"] is ExtractedOpportunity


def test_extract_truncates_long_content(monkeypatch):
    """Tavily の全文は 40,000 文字を超えることがある。そのまま渡さない。"""
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return _Result(_extracted())

    monkeypatch.setattr(extraction, "generate_structured", fake)
    extraction.extract_opportunity("https://e.com", "あ" * 50_000)

    assert "あ" * MAX_PAGE_CONTENT_CHARS in seen["user"]
    assert "あ" * (MAX_PAGE_CONTENT_CHARS + 1) not in seen["user"]


def test_extract_returns_utc(monkeypatch):
    monkeypatch.setattr(
        extraction,
        "generate_structured",
        lambda **_: _Result(_extracted(start_at="2026-09-21T19:00:00+09:00")),
    )
    out = extraction.extract_opportunity("https://e.com", "本文")
    assert out.start_at == datetime(2026, 9, 21, 10, 0, tzinfo=UTC)


# --- extract_many ---------------------------------------------------------


def test_extract_many_partial_failure_keeps_rest(monkeypatch):
    """1 件の失敗で全体を捨てない。"""
    calls = []

    def fake(**kwargs):
        calls.append(kwargs["user"])
        if "ng.com" in kwargs["user"]:
            raise LLMValidationError("壊れたページ")
        return _Result(_extracted())

    monkeypatch.setattr(extraction, "generate_structured", fake)
    sources = [
        SearchResult(title="a", url="https://ok.com", snippet="s", content="本文"),
        SearchResult(title="b", url="https://ng.com", snippet="s", content="本文"),
        SearchResult(title="c", url="https://ok2.com", snippet="s", content="本文"),
    ]
    extracted, failed = extraction.extract_many(sources)

    assert len(extracted) == 2
    assert failed == ["https://ng.com"]
    assert len(calls) == 3


def test_extract_many_skips_sources_without_content(monkeypatch):
    monkeypatch.setattr(extraction, "generate_structured", lambda **_: _Result(_extracted()))
    sources = [
        SearchResult(title="a", url="https://empty.com", snippet="", content=None),
        SearchResult(title="b", url="https://ok.com", snippet="s", content="本文"),
    ]
    extracted, failed = extraction.extract_many(sources)

    assert len(extracted) == 1
    assert failed == ["https://empty.com"]


def test_extract_many_accepts_page_content(monkeypatch):
    """read_page の戻り値もそのまま渡せる。"""
    monkeypatch.setattr(extraction, "generate_structured", lambda **_: _Result(_extracted()))
    pages = [PageContent(url="https://e.com", title="t", content="本文")]
    extracted, failed = extraction.extract_many(pages)

    assert len(extracted) == 1
    assert failed == []


def test_extract_many_falls_back_to_snippet(monkeypatch):
    """検索の content が無ければ snippet を使う。"""
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return _Result(_extracted())

    monkeypatch.setattr(extraction, "generate_structured", fake)
    extraction.extract_many(
        [SearchResult(title="a", url="https://e.com", snippet="抜粋のみ", content=None)]
    )
    assert "抜粋のみ" in seen["user"]


def test_extract_many_empty_input(monkeypatch):
    monkeypatch.setattr(extraction, "generate_structured", lambda **_: _Result(_extracted()))
    assert extraction.extract_many([]) == ([], [])


def test_failure_log_does_not_leak_page_content(monkeypatch, caplog):
    """ページ本文を Log へ出さない。"""

    def fake(**_):
        raise LLMValidationError("schema mismatch")

    monkeypatch.setattr(extraction, "generate_structured", fake)
    with caplog.at_level("WARNING"):
        extraction.extract_many(
            [
                SearchResult(
                    title="a",
                    url="https://e.com",
                    snippet="s",
                    content="秘密のページ本文",
                )
            ]
        )
    assert "秘密のページ本文" not in caplog.text


def test_extract_raises_default_max_tokens(monkeypatch):
    """既定の 2048 では gemini の reasoning で JSON が途中で切れる。"""
    seen = {}

    def fake(**kwargs):
        seen.update(kwargs)
        return _Result(_extracted())

    monkeypatch.setattr(extraction, "generate_structured", fake)
    extraction.extract_opportunity("https://e.com", "本文")

    assert seen["max_tokens"] == extraction.EXTRACTION_MAX_TOKENS
    assert seen["max_tokens"] >= 8192
