"""検索 Provider。

MVP は Tavily。別 provider（Brave / Serper など）への差し替えは
`SearchProvider` を実装して `get_provider()` を差し替えるだけでよい。
比較と選定は Search Cost Optimization（P2）で行う。
"""

from functools import lru_cache

from tools.search.base import PageContent, SearchError, SearchProvider, SearchResult
from tools.search.tavily import TavilyProvider


@lru_cache
def get_provider() -> SearchProvider:
    """プロセス内で使い回す provider。接続を毎回張り直さない。"""
    return TavilyProvider()


def close_provider() -> None:
    """アプリ終了時に接続を閉じる。main.py の lifespan から呼ぶ。"""
    if get_provider.cache_info().currsize:
        get_provider().close()
        get_provider.cache_clear()


__all__ = [
    "PageContent",
    "SearchError",
    "SearchProvider",
    "SearchResult",
    "TavilyProvider",
    "close_provider",
    "get_provider",
]
