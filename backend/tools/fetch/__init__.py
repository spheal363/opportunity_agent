"""本文取得（Page Fetcher）。

**検索 provider とは別の軸。** Serper のように検索しか持たない provider へ
差し替えても、本文取得は独立して選べる。

  PAGE_FETCHER=tavily   Tavily Extract（既定・現行）
  PAGE_FETCHER=jina     Jina Reader（実験用。キー無しでも動く）

既定値は比較（#65）で採用が決まるまで現行のまま変えない。
"""

from functools import lru_cache

from config import get_settings
from tools.fetch.base import FetchError, PageContent, PageFetcher
from tools.fetch.jina import JinaReaderFetcher
from tools.fetch.tavily import TavilyExtractFetcher

_FETCHERS: dict[str, type[PageFetcher]] = {
    "tavily": TavilyExtractFetcher,
    "jina": JinaReaderFetcher,
}


@lru_cache
def get_fetcher() -> PageFetcher:
    """プロセス内で使い回す fetcher。接続を毎回張り直さない。"""
    name = (get_settings().page_fetcher or "tavily").strip().lower()
    cls = _FETCHERS.get(name)
    if cls is None:
        raise FetchError(
            f"PAGE_FETCHER の値が不正です: {name}（{'/'.join(sorted(_FETCHERS))} のいずれか）"
        )
    return cls()


def close_fetcher() -> None:
    """アプリ終了時に接続を閉じる。main.py の lifespan から呼ぶ。"""
    if get_fetcher.cache_info().currsize:
        get_fetcher().close()
        get_fetcher.cache_clear()


__all__ = [
    "FetchError",
    "JinaReaderFetcher",
    "PageContent",
    "PageFetcher",
    "TavilyExtractFetcher",
    "close_fetcher",
    "get_fetcher",
]
