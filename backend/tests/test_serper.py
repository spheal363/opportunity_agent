"""Serper provider のテスト。

ネットワークへは出ない。httpx.MockTransport で応答を差し替える。

**確かめたいのは「Serper に extract を持つふりをさせない」こと。**
検索 provider を替えただけでは本文不足は解決しない、という前提が
コードの上でも崩れていないかを見る。
"""

import httpx
import pytest

from config import Settings
from tools.search import SearchError, get_provider
from tools.search.serper import MAX_QUERY_CHARS, MAX_SEARCH_RESULTS, SerperProvider


def _settings(**overrides) -> Settings:
    base = {"serper_api_key": "serper-test"}
    base.update(overrides)
    return Settings(**base)


def _provider(handler, **overrides) -> SerperProvider:
    return SerperProvider(
        _settings(**overrides), client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _organic(**overrides) -> dict:
    base = {
        "title": "AI Agent Hackathon 2026",
        "link": "https://example-hack.jp/agent-2026",
        "snippet": "AI Agent をテーマにした 2 日間のハッカソン。",
        "position": 1,
    }
    base.update(overrides)
    return base


def test_does_not_claim_to_fetch_pages():
    """**本文取得を持つふりをさせない。**

    Serper は title / link / snippet しか返さない。ここが True になると
    Page Reader が本文取得を任せてしまい、抽出の入力が痩せたまま気づけない。
    """
    assert SerperProvider.supports_extract is False


def test_snippet_is_not_copied_into_content():
    """snippet を content に流用しない。

    流用すると抽出側が「本文がある」と誤認し、本文取得を挟む判断ができなくなる。
    """
    p = _provider(lambda r: httpx.Response(200, json={"organic": [_organic()]}))
    [result] = p.search("ハッカソン")

    assert result.snippet
    assert result.content is None


def test_sends_japanese_region_and_language():
    """日本語のイベントを探す用途に合わせる。

    既定が英語圏のままだと、Tavily との比較が実際の用途とずれる。
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"organic": []})

    _provider(handler).search("ハッカソン")

    assert seen["gl"] == "jp"
    assert seen["hl"] == "ja"


def test_position_is_not_used_as_relevance_score():
    """掲載順は関連度ではない。順位付けの主軸にしない。"""
    p = _provider(lambda r: httpx.Response(200, json={"organic": [_organic(position=1)]}))
    [result] = p.search("q")

    assert result.score is None


def test_missing_key_is_reported_before_sending():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("キーが無いのにリクエストを投げている")

    p = _provider(handler, serper_api_key=None)
    with pytest.raises(SearchError, match="SERPER_API_KEY"):
        p.search("q")


def test_empty_query_is_rejected():
    p = _provider(lambda r: httpx.Response(200, json={"organic": []}))
    with pytest.raises(SearchError):
        p.search("   ")


def test_long_query_is_truncated_not_rejected():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"organic": []})

    _provider(handler).search("あ" * (MAX_QUERY_CHARS + 50))
    assert len(seen["q"]) == MAX_QUERY_CHARS


def test_limit_is_clamped():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json={"organic": []})

    _provider(handler).search("q", limit=999)
    assert seen["num"] == MAX_SEARCH_RESULTS


@pytest.mark.parametrize(
    ("status", "retryable"),
    [(429, True), (500, True), (503, True), (401, False), (422, False)],
)
def test_error_status_is_classified(status, retryable):
    p = _provider(lambda r: httpx.Response(status))
    with pytest.raises(SearchError) as exc:
        p.search("q")
    assert exc.value.retryable is retryable


def test_missing_organic_is_an_error_not_zero_results():
    """`organic` が無いのは「0 件」ではなく「形が想定と違う」。

    0 件として返すと、レスポンス形式が変わったことに気づけない。
    """
    p = _provider(lambda r: httpx.Response(200, json={"searchParameters": {}}))
    with pytest.raises(SearchError):
        p.search("q")


def test_entry_without_link_is_skipped():
    p = _provider(
        lambda r: httpx.Response(200, json={"organic": [{"title": "no link"}, _organic()]})
    )
    assert len(p.search("q")) == 1


def test_provider_is_selected_by_setting(monkeypatch):
    """**既定は serper（構成 C）。** A へ戻すには tavily を指定する。"""
    from config import Settings as S

    assert S(_env_file=None).search_provider == "serper"

    get_provider.cache_clear()
    monkeypatch.setattr("tools.search.get_settings", lambda: _settings(search_provider="tavily"))
    try:
        assert get_provider().name == "tavily"
    finally:
        get_provider.cache_clear()


def test_unknown_provider_name_is_rejected(monkeypatch):
    get_provider.cache_clear()
    monkeypatch.setattr("tools.search.get_settings", lambda: _settings(search_provider="brave"))
    try:
        with pytest.raises(SearchError, match="SEARCH_PROVIDER"):
            get_provider()
    finally:
        get_provider.cache_clear()
