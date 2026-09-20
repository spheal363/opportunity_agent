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
from tools.search.tavily import (
    MAX_EXTRACT_URLS,
    MAX_QUERY_CHARS,
    MAX_SEARCH_RESULTS,
    TavilyProvider,
)


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


@pytest.mark.parametrize(
    "body",
    [
        {"unexpected": True},  # results が無い
        {"results": "not-a-list"},  # results が list でない
    ],
)
def test_malformed_response_is_retryable(body):
    """provider の失敗はすべて SearchError に寄せる。

    AttributeError が漏れると retryable の分類を迂回して Agent Run 全体が落ちる。
    """
    p = _provider(lambda r: httpx.Response(200, json=body))
    with pytest.raises(SearchError) as exc:
        p.search("q")
    assert exc.value.retryable is True


@pytest.mark.parametrize("broken", [None, 42, "text", []])
def test_non_dict_items_are_skipped_not_raised(broken):
    """要素が dict でなくても AttributeError を漏らさない。"""
    p = _provider(lambda r: httpx.Response(200, json=_body(_result(), broken)))
    results = p.search("q")
    assert len(results) == 1


@pytest.mark.parametrize(
    "body",
    [
        {"results": 5, "failed_results": []},
        {"results": [], "failed_results": 5},
        {"results": {"a": 1}, "failed_results": []},
        {"results": "text", "failed_results": []},
    ],
)
def test_extract_malformed_container_is_retryable(body):
    """search() 側と対称にする。

    コンテナ自体が list でないと for 文が TypeError を投げ、
    provider の失敗を SearchError に寄せる設計を迂回する。
    """
    p = _provider(lambda r: httpx.Response(200, json=body))
    with pytest.raises(SearchError) as exc:
        p.extract(["https://a.com"])
    assert exc.value.retryable is True


@pytest.mark.parametrize("broken", [None, 42, "text"])
def test_extract_non_dict_items_are_skipped(broken):
    p = _provider(
        lambda r: httpx.Response(200, json=_extract_body(_page(), broken, failed=[broken]))
    )
    pages, failed = p.extract(["https://a.com"])
    assert len(pages) == 1
    assert failed == []


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


# --- ページ取得（#17）----------------------------------------------------


def _extract_body(*results: dict, failed: list | None = None) -> dict:
    return {
        "results": list(results),
        "failed_results": failed or [],
        "response_time": 0.7,
    }


def _page(**overrides) -> dict:
    base = {
        "url": "https://example.com/hackathon",
        "title": "AI Hackathon Tokyo",
        "raw_content": "ページ本文" * 100,
        "images": [],
    }
    base.update(overrides)
    return base


def test_extract_request_shape():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["url"] = str(request.url)
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_extract_body(_page()))

    _provider(handler).extract(["https://a.com", "https://b.com"])

    assert seen["url"] == "https://api.tavily.com/extract"
    # 複数 URL は 1 リクエストにまとめる
    assert seen["body"]["urls"] == ["https://a.com", "https://b.com"]


def test_extract_maps_to_page_content():
    p = _provider(lambda r: httpx.Response(200, json=_extract_body(_page())))
    pages, failed = p.extract(["https://example.com/hackathon"])

    assert failed == []
    assert len(pages) == 1
    assert pages[0].url == "https://example.com/hackathon"
    assert pages[0].title == "AI Hackathon Tokyo"
    assert len(pages[0].content) == 500


def test_extract_partial_failure_does_not_raise():
    """一部が落ちても残りを捨てない。Tavily は HTTP 200 で failed_results を返す。"""
    p = _provider(
        lambda r: httpx.Response(
            200,
            json=_extract_body(
                _page(),
                failed=[{"url": "https://broken.example", "error": "Failed to fetch url"}],
            ),
        )
    )
    pages, failed = p.extract(["https://example.com/hackathon", "https://broken.example"])

    assert len(pages) == 1
    assert failed == ["https://broken.example"]


def test_url_without_content_is_reported_as_failed():
    """HTTP 200 だが本文が無い URL を黙って捨てない。

    捨てると、要求した URL が pages にも failed にも現れなくなる。
    """
    p = _provider(
        lambda r: httpx.Response(
            200,
            json=_extract_body(
                _page(url="https://ok.com"),
                _page(url="https://empty.com", raw_content=None),
            ),
        )
    )
    requested = ["https://ok.com", "https://empty.com"]
    pages, failed = p.extract(requested)

    assert [x.url for x in pages] == ["https://ok.com"]
    assert failed == ["https://empty.com"]
    # 要求した URL は必ずどちらかに現れる
    assert set(requested) == {x.url for x in pages} | set(failed)


def test_extract_with_empty_urls_does_not_call_api():
    called = []

    def handler(request: httpx.Request) -> httpx.Response:
        called.append(1)
        return httpx.Response(200, json=_extract_body())

    pages, failed = _provider(handler).extract([])
    assert (pages, failed, called) == ([], [], [])


def test_extract_error_is_classified():
    p = _provider(lambda r: httpx.Response(429, json={"detail": "rate limit"}))
    with pytest.raises(SearchError) as exc:
        p.extract(["https://a.com"])
    assert exc.value.retryable is True


def test_tavily_supports_extract():
    assert _provider(lambda r: httpx.Response(200)).supports_extract is True


def test_provider_without_extract_raises():
    """Brave / Serper のように検索のみの provider へ差し替えたとき。"""
    from tools.search.base import SearchProvider

    class SearchOnly(SearchProvider):
        name = "search-only"

        def search(self, query, *, limit=10):
            return []

    with pytest.raises(SearchError, match="ページ取得に対応していません"):
        SearchOnly().extract(["https://a.com"])


# --- Page Reader Tool -----------------------------------------------------


def test_page_reader_is_registered_as_auto():
    assert registry.get("read_page").permission is PermissionLevel.AUTO


def test_page_reader_accepts_single_and_multiple_urls(monkeypatch):
    from tools.search.base import PageContent

    seen = {}

    class Fake:
        name = "fake"
        supports_extract = True

        def extract(self, urls):
            seen["urls"] = urls
            return [PageContent(url=u, title="t", content="c") for u in urls], []

    monkeypatch.setattr("tools.page_reader.get_provider", lambda: Fake())

    out = registry.invoke("read_page", url="https://a.com")
    assert seen["urls"] == ["https://a.com"]
    assert out.external is True
    assert len(out.data["pages"]) == 1

    registry.invoke("read_page", url=["https://a.com", "https://b.com"])
    assert seen["urls"] == ["https://a.com", "https://b.com"]


def test_page_reader_reports_failed_urls(monkeypatch):
    from tools.search.base import PageContent

    class Fake:
        name = "fake"
        supports_extract = True

        def extract(self, urls):
            return [PageContent(url=urls[0], title="t", content="c")], [urls[1]]

    monkeypatch.setattr("tools.page_reader.get_provider", lambda: Fake())
    out = registry.invoke("read_page", url=["https://ok.com", "https://ng.com"])

    assert len(out.data["pages"]) == 1
    assert out.data["failed"] == ["https://ng.com"]


# --- 入力の検証（レビュー指摘）--------------------------------------------


def test_query_is_required():
    p = _provider(lambda r: httpx.Response(200, json=_body()))
    with pytest.raises(SearchError, match="空です"):
        p.search("   ")


def test_long_query_is_truncated():
    """長すぎる検索語はトークンとコストだけ増やす。"""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_body(_result()))

    _provider(handler).search("あ" * 1000)
    assert len(seen["body"]["query"]) == MAX_QUERY_CHARS


@pytest.mark.parametrize("asked,sent", [(0, 1), (-5, 1), (5, 5), (50, MAX_SEARCH_RESULTS)])
def test_limit_is_clamped(asked, sent):
    """API 側は大きな値を黙って頭打ちにする。ここで揃える。"""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_body(_result()))

    _provider(handler).search("q", limit=asked)
    assert seen["body"]["max_results"] == sent


def test_extract_rejects_too_many_urls():
    """実測: 21 件以上は Tavily が HTTP 400 を返す。手前で弾く。"""
    p = _provider(lambda r: httpx.Response(200, json=_extract_body()))
    with pytest.raises(SearchError, match="20 件まで"):
        p.extract([f"https://e{i}.com" for i in range(MAX_EXTRACT_URLS + 1)])


def test_extract_accepts_max_urls():
    p = _provider(lambda r: httpx.Response(200, json=_extract_body()))
    p.extract([f"https://e{i}.com" for i in range(MAX_EXTRACT_URLS)])


# --- page_reader の入力検証（レビュー指摘）--------------------------------


@pytest.mark.parametrize(
    "bad", ["file:///etc/passwd", "data:text/html,x", "javascript:alert(1)", "ftp://e.com/x"]
)
def test_page_reader_rejects_non_http_schemes(monkeypatch, bad):
    """file: や data: を Agent に踏ませない。"""
    from tools.search.base import PageContent

    called = []

    class Fake:
        name = "fake"
        supports_extract = True

        def extract(self, urls):
            called.append(urls)
            return [PageContent(url=u, title="t", content="c") for u in urls], []

    monkeypatch.setattr("tools.page_reader.get_provider", lambda: Fake())
    out = registry.invoke("read_page", url=["https://ok.com", bad])

    # provider には渡さない
    assert called == [["https://ok.com"]]
    # だが「取れなかった」事実としては残す
    assert out.data["failed"] == [bad]


def test_page_reader_with_only_bad_urls_does_not_call_provider(monkeypatch):
    called = []

    class Fake:
        name = "fake"
        supports_extract = True

        def extract(self, urls):
            called.append(urls)
            return [], []

    monkeypatch.setattr("tools.page_reader.get_provider", lambda: Fake())
    out = registry.invoke("read_page", url="file:///etc/passwd")

    assert called == []
    assert out.data["failed"] == ["file:///etc/passwd"]


def test_page_reader_truncates_huge_content(monkeypatch):
    """実測で 43,910 文字のページがあった。際限なく持たない。"""
    from tools.page_reader import MAX_CONTENT_CHARS
    from tools.search.base import PageContent

    class Fake:
        name = "fake"
        supports_extract = True

        def extract(self, urls):
            return [PageContent(url=urls[0], title="t", content="あ" * 200_000)], []

    monkeypatch.setattr("tools.page_reader.get_provider", lambda: Fake())
    out = registry.invoke("read_page", url="https://e.com")

    assert len(out.data["pages"][0].content) == MAX_CONTENT_CHARS
