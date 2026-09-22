"""本文取得（Page Fetcher）のテスト。

ネットワークへは出ない。httpx.MockTransport で応答を差し替える。

**確かめたいのは 2 つ。**

  1. 検索と本文取得を別々に選べること
  2. 取得経路を増やしても、内部アドレスを踏ませない保護が残っていること
"""

import httpx
import pytest

from config import Settings
from tools.fetch import FetchError, get_fetcher
from tools.fetch.jina import JinaReaderFetcher
from tools.fetch.tavily import TavilyExtractFetcher
from tools.search.base import PageContent
from tools.urlcheck import is_fetchable


def _settings(**overrides) -> Settings:
    return Settings(**overrides)


def _jina(handler, **overrides) -> JinaReaderFetcher:
    return JinaReaderFetcher(
        _settings(**overrides), client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _ok(url: str, content: str = "本文") -> httpx.Response:
    return httpx.Response(200, json={"data": {"url": url, "title": "t", "content": content}})


# --- 検索と本文取得を別々に選ぶ ---------------------------------------------


def test_the_default_fetcher_is_jina():
    """**既定は jina（構成 C）。** キー無しでも動く。"""
    assert Settings(_env_file=None).page_fetcher == "jina"


def test_fetcher_is_selected_by_setting(monkeypatch):
    get_fetcher.cache_clear()
    monkeypatch.setattr("tools.fetch.get_settings", lambda: _settings(page_fetcher="jina"))
    try:
        assert get_fetcher().name == "jina"
    finally:
        get_fetcher.cache_clear()


def test_unknown_fetcher_name_is_rejected(monkeypatch):
    get_fetcher.cache_clear()
    monkeypatch.setattr("tools.fetch.get_settings", lambda: _settings(page_fetcher="magic"))
    try:
        with pytest.raises(FetchError, match="PAGE_FETCHER"):
            get_fetcher()
    finally:
        get_fetcher.cache_clear()


def test_fetcher_does_not_depend_on_search_provider(monkeypatch):
    """Serper 検索でも本文取得は Tavily を選べる。

    ここが繋がっていると「検索を替えると本文も失う」ことになる。
    """
    get_fetcher.cache_clear()
    monkeypatch.setattr(
        "tools.fetch.get_settings",
        lambda: _settings(search_provider="serper", page_fetcher="tavily"),
    )
    try:
        assert isinstance(get_fetcher(), TavilyExtractFetcher)
    finally:
        get_fetcher.cache_clear()


# --- Jina Reader -------------------------------------------------------------


def test_jina_returns_pages_and_failures():
    def handler(request: httpx.Request) -> httpx.Response:
        if "ng.com" in str(request.url):
            return httpx.Response(500)
        return _ok("https://ok.com")

    pages, failed = _jina(handler).fetch(["https://ok.com", "https://ng.com"])

    assert [p.url for p in pages] == ["https://ok.com"]
    assert failed == ["https://ng.com"]


def test_jina_every_requested_url_is_accounted_for():
    """要求した URL は必ず pages か failed のどちらかに現れる。

    どちらにも現れないと、呼び出し元は「取れなかった」ことに気づけない。
    """
    urls = ["https://a.com", "https://b.com", "https://c.com"]

    def handler(request: httpx.Request) -> httpx.Response:
        if "b.com" in str(request.url):
            return httpx.Response(200, json={"data": {"content": ""}})
        return _ok(str(request.url))

    pages, failed = _jina(handler).fetch(urls)
    assert sorted([p.url for p in pages] + failed) == sorted(urls)


def test_jina_uses_the_requested_url_not_the_normalized_one():
    """応答に入る URL ではなく、要求した URL を返す。

    Jina 側が正規化した値を使うと、呼び出し元が持つ候補の URL と一致せず、
    「要求した URL がどちらにも現れない」状態になる。
    """
    p = _jina(lambda r: _ok("https://example.jp/x/"))
    pages, failed = p.fetch(["https://example.jp/x"])

    assert [x.url for x in pages] == ["https://example.jp/x"]
    assert failed == []


def test_jina_works_without_an_api_key():
    """**キー無しでも動く。** 新規契約なしで実験できることが選定理由。"""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["auth"] = request.headers.get("authorization")
        return _ok("https://a.com")

    p = _jina(handler, jina_api_key=None)
    pages, _ = p.fetch(["https://a.com"])

    assert len(pages) == 1
    assert seen["auth"] is None


def test_jina_concurrency_is_lower_without_a_key():
    """キー無しは 20 RPM。並列度を上げても 429 を踏むだけ。"""
    assert (
        _jina(lambda r: _ok("x"), jina_api_key=None).workers
        < _jina(lambda r: _ok("x"), jina_api_key="k").workers
    )


def test_jina_bad_json_is_a_failure_not_a_crash():
    p = _jina(lambda r: httpx.Response(200, content=b"<html>not json</html>"))
    pages, failed = p.fetch(["https://a.com"])

    assert pages == []
    assert failed == ["https://a.com"]


def test_jina_empty_body_counts_as_failure():
    """HTTP 200 でも本文が無ければ取れていない。

    成功として扱うと、空本文のまま抽出へ進んで原因が見えなくなる。
    """
    p = _jina(lambda r: httpx.Response(200, json={"data": {"content": ""}}))
    pages, failed = p.fetch(["https://a.com"])

    assert pages == []
    assert failed == ["https://a.com"]


def test_jina_empty_input_makes_no_request():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("URL が無いのにリクエストを投げている")

    assert _jina(handler).fetch([]) == ([], [])


# --- Tavily Extract の分割 ---------------------------------------------------


def test_tavily_fetcher_splits_beyond_the_api_limit():
    """21 件以上は HTTP 400。呼び出し側に上限を意識させず、ここで分ける。"""

    class FakeProvider:
        def __init__(self):
            self.batches = []

        def extract(self, urls):
            self.batches.append(len(urls))
            return [PageContent(url=u, title="t", content="c") for u in urls], []

        def close(self):
            pass

    provider = FakeProvider()
    urls = [f"https://e{i}.com" for i in range(25)]
    pages, failed = TavilyExtractFetcher(provider).fetch(urls)

    assert provider.batches == [20, 5]
    assert len(pages) == 25
    assert failed == []


# --- 取得経路が増えても保護は残る -------------------------------------------


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1/x",
        "http://localhost/x",
        "http://169.254.169.254/latest/meta-data/",
        "http://2130706433/x",
        "http://0x7f000001/x",
        "http://127.0x0.0.1/x",
        "http://127.1/x",
        "file:///etc/passwd",
        "http://internal/x",
    ],
)
def test_internal_addresses_are_still_rejected(url):
    """**経路を増やしても塞ぎ続ける。**

    Jina Reader は取得を外部サービスが行うが、こちらが内部アドレスを
    渡してよい理由にはならない。判定は `tools/urlcheck.py` の 1 か所。
    """
    assert is_fetchable(url) is False


@pytest.mark.parametrize(
    "url",
    ["https://connpass.com/event/1", "http://example-hack.jp/x", "https://xn--eckwd4c7c.jp/a"],
)
def test_normal_hosts_are_allowed(url):
    assert is_fetchable(url) is True


def test_page_reader_never_hands_internal_urls_to_the_fetcher(monkeypatch):
    """Page Reader は fetcher へ渡す前に落とす。"""
    from tools import registry

    seen = {}

    class Fake:
        name = "fake"

        def fetch(self, urls):
            seen["urls"] = urls
            return [PageContent(url=u, title="t", content="c") for u in urls], []

    monkeypatch.setattr("tools.page_reader.get_fetcher", lambda: Fake())
    out = registry.invoke("read_page", url=["https://ok.jp/a", "http://169.254.169.254/x"])

    assert seen["urls"] == ["https://ok.jp/a"]
    assert out.data["failed"] == ["http://169.254.169.254/x"]


def test_page_reader_counts_attempts_and_successes(monkeypatch):
    """**試した数と取れた数を分けて数える。**

    取れなかった分も、そのサービスの使用量としては発生している。
    """
    from ai import cost
    from tools import registry

    class Fake:
        name = "fake"

        def fetch(self, urls):
            return [PageContent(url=urls[0], title="t", content="c")], [urls[1]]

    monkeypatch.setattr("tools.page_reader.get_fetcher", lambda: Fake())
    with cost.track() as tracker:
        registry.invoke("read_page", url=["https://a.jp/x", "https://b.jp/y"])

    out = tracker.to_dict()
    assert out["extract_calls"] == 2
    assert out["extract_successes"] == 1


# --- 不正な URL で巻き添えにしない（PR #10 の指摘）--------------------------
#
# **URL は LLM がページ本文から読み取った値。** ページの書き手が仕込める。
# 制御文字を含む URL 1 件で、正常な候補まで取得できなくなっていた。


@pytest.mark.parametrize(
    "url",
    [
        "http://ok.jp/a\r\nX-Injected: 1",
        "http://ok.jp/a\nX",
        "http://ok.jp/a\tb",
        "http://ok.jp/a\x00b",
        "http://ok.jp/a\x7fb",
    ],
)
def test_a_url_with_control_characters_is_rejected(url):
    """**根本はここで落とす。** 取得経路が増えても効く。"""
    assert is_fetchable(url) is False


@pytest.mark.parametrize(
    "url",
    [
        # **生の空白は落とさない。** httpx が %20 へ直して通すので、
        # 落とすと取得できたはずの候補を捨てることになる。
        "https://example.jp/my page.html",
        "https://example.jp/a%20b",
        "https://example.jp/日本語/ページ",
        "https://example.jp/a?q=%E6%97%A5&x=1",
        "https://user:pass@example.jp/a",
        "https://example.jp:8443/a#frag",
    ],
)
def test_a_fetchable_url_is_not_dropped(url):
    """**落としすぎない。** 取得できるものを捨てると機会を失う。"""
    assert is_fetchable(url) is True


def test_one_malformed_url_does_not_take_the_others_down():
    """**1 件の不正な URL で、正常な候補まで捨てない。**

    Jina は URL をパスに連結するので、漏れると `httpx.InvalidURL` が飛ぶ。
    これは `httpx.HTTPError` の**サブクラスではない**ため、以前は
    `except httpx.HTTPError` で拾えず、fetch 全体が落ちていた。
    """
    assert issubclass(httpx.InvalidURL, httpx.HTTPError) is False

    urls = ["https://good1.jp/a", "http://ok.jp/a\r\nX", "https://good2.jp/b"]
    pages, failed = _jina(lambda r: _ok("https://good1.jp/a")).fetch(urls)

    assert len(pages) == 2, "正常な候補まで落ちている"
    assert failed == ["http://ok.jp/a\r\nX"]


def test_the_tool_does_not_leak_the_exception(monkeypatch):
    """`read_page` の外へ例外を漏らさない。

    漏れると `agent/loop.py` の `_with_bodies` は `except SearchError` しか
    見ていないので、**run 全体が failed になる。**
    """
    from tools import registry

    class Fake:
        name = "fake"

        def fetch(self, urls):
            return [PageContent(url=u, title="t", content="c") for u in urls], []

    monkeypatch.setattr("tools.page_reader.get_fetcher", lambda: Fake())
    out = registry.invoke("read_page", url=["https://ok.jp/a", "http://ng.jp/a\r\nX"])

    assert [p.url for p in out.data["pages"]] == ["https://ok.jp/a"]
    assert out.data["failed"] == ["http://ng.jp/a\r\nX"]


def test_the_filter_matches_exactly_what_httpx_can_handle():
    """**判定と httpx の限界がずれていないこと。**

    ずれ方は 2 通りあり、どちらも困る。

      判定を通るのに httpx が落ちる -> 1 件で他の候補まで巻き添えになる
      httpx は通すのに判定が落とす   -> 取得できたはずの候補を捨てる

    ASCII を全部なめて、両方が 0 であることを確かめる。**httpx の側が
    変わったら気づける。**
    """
    client = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200)))

    leaks: list[str] = []
    over_blocked: list[str] = []
    for code in range(0x80):
        url = f"https://example.jp/a{chr(code)}b"
        allowed = is_fetchable(url)
        try:
            client.get("https://r.jina.ai/" + url)
            httpx_breaks = False
        except httpx.InvalidURL:
            httpx_breaks = True
        except httpx.HTTPError:
            httpx_breaks = False

        if allowed and httpx_breaks:
            leaks.append(hex(code))
        if not allowed and not httpx_breaks:
            over_blocked.append(hex(code))

    assert leaks == [], f"判定を通るのに httpx が落ちる: {leaks}"
    assert over_blocked == [], f"httpx は通すのに判定が落とす: {over_blocked}"
