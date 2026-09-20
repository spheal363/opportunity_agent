"""Web Search Tool と Tavily provider のテスト。

ネットワークへは出ない。httpx.MockTransport で応答を差し替える。
"""

import json

import httpx
import pytest

from config import Settings
from tools import registry
from tools.base import PermissionLevel, ToolResult
from tools.search import SearchError, SearchResult
from tools.search.tavily import TavilyProvider


def _settings(**overrides) -> Settings:
    base = {"search_api_key": "tvly-dev-test"}
    base.update(overrides)
    return Settings(**base)


def _provider(handler, **overrides) -> TavilyProvider:
    return TavilyProvider(
        _settings(**overrides), client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _body(*results: dict) -> dict:
    return {"query": "q", "response_time": 1.0, "results": list(results)}


def _result(**overrides) -> dict:
    base = {
        "title": "AI Hackathon Tokyo",
        "url": "https://example.com/hackathon",
        "content": "AIと音楽をテーマにしたハッカソン。",
        "score": 0.9,
        "raw_content": None,
        "id": "abc",
    }
    base.update(overrides)
    return base


# --- 設定 ---------------------------------------------------------------


def test_is_configured():
    assert _provider(lambda r: httpx.Response(200)).is_configured is True
    assert _provider(lambda r: httpx.Response(200), search_api_key=None).is_configured is False


def test_missing_key_raises():
    p = _provider(lambda r: httpx.Response(200, json=_body()), search_api_key=None)
    with pytest.raises(SearchError, match="SEARCH_API_KEY"):
        p.search("q")


# --- リクエストの組み立て -------------------------------------------------


def test_request_shape():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_body(_result()))

    _provider(handler).search("AI hackathon", limit=5)

    assert seen["url"] == "https://api.tavily.com/search"
    assert seen["auth"] == "Bearer tvly-dev-test"
    assert seen["body"]["query"] == "AI hackathon"
    assert seen["body"]["max_results"] == 5
    # 全文はトークンを食うため既定では取らない
    assert seen["body"]["include_raw_content"] is False


def test_raw_content_can_be_requested():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_body(_result()))

    _provider(handler).search("q", include_raw_content=True)
    assert seen["body"]["include_raw_content"] is True


# --- レスポンスの変換 -----------------------------------------------------


def test_maps_to_search_result():
    p = _provider(lambda r: httpx.Response(200, json=_body(_result())))
    results = p.search("q")

    assert len(results) == 1
    r = results[0]
    assert isinstance(r, SearchResult)
    assert r.title == "AI Hackathon Tokyo"
    assert r.url == "https://example.com/hackathon"
    assert r.content == "AIと音楽をテーマにしたハッカソン。"
    assert r.score == 0.9


def test_raw_content_takes_precedence_over_content():
    """全文を取得したならそちらを content にする。"""
    p = _provider(
        lambda r: httpx.Response(200, json=_body(_result(raw_content="ページ全文" * 100)))
    )
    assert len(p.search("q")[0].content) == 500


def test_snippet_is_truncated():
    p = _provider(lambda r: httpx.Response(200, json=_body(_result(content="あ" * 1000))))
    r = p.search("q")[0]
    assert len(r.snippet) == 300
    assert len(r.content) == 1000


def test_result_without_url_is_skipped():
    p = _provider(
        lambda r: httpx.Response(200, json=_body(_result(), _result(url=None, title="壊れた")))
    )
    results = p.search("q")
    assert len(results) == 1
    assert results[0].title == "AI Hackathon Tokyo"


def test_missing_optional_fields():
    """provider が一部のフィールドを返さなくても落ちない。"""
    p = _provider(lambda r: httpx.Response(200, json=_body({"url": "https://example.com"})))
    r = p.search("q")[0]
    assert r.title == ""
    assert r.snippet == ""
    assert r.content is None
    assert r.score is None


def test_malformed_response_is_retryable():
    p = _provider(lambda r: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(SearchError) as exc:
        p.search("q")
    assert exc.value.retryable is True


# --- エラー分類 ----------------------------------------------------------


@pytest.mark.parametrize(
    "status,retryable",
    [(429, True), (500, True), (503, True), (401, False), (422, False), (400, False)],
)
def test_status_code_classification(status, retryable):
    p = _provider(lambda r: httpx.Response(status, json={"detail": "nope"}))
    with pytest.raises(SearchError) as exc:
        p.search("q")
    assert exc.value.status_code == status
    assert exc.value.retryable is retryable


def test_timeout_is_retryable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    with pytest.raises(SearchError) as exc:
        _provider(handler).search("q")
    assert exc.value.retryable is True


def test_error_does_not_leak_api_key():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(SearchError) as exc:
        _provider(handler).search("q")
    assert "tvly-dev-test" not in str(exc.value)


# --- Tool としての登録 ----------------------------------------------------


def test_tool_is_registered_as_auto():
    tool = registry.get("search_web")
    assert tool.permission is PermissionLevel.AUTO


def test_tool_returns_untrusted_result(monkeypatch):
    """検索結果は Untrusted Data として返す。"""

    class Fake:
        name = "fake"

        def search(self, query, *, limit=10):
            return [SearchResult(title="t", url="https://e.com", snippet="s")]

    monkeypatch.setattr("tools.web_search.get_provider", lambda: Fake())
    out = registry.invoke("search_web", query="q")

    assert isinstance(out, ToolResult)
    assert out.external is True
    assert out.data[0].url == "https://e.com"
