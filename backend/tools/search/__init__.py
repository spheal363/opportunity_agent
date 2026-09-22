"""検索 Provider。

  SEARCH_PROVIDER=tavily   既定・現行。検索結果に本文抜粋が付く
  SEARCH_PROVIDER=serper   比較用（#65）。**本文は返らない**

既定値は比較で採用が決まるまで現行のまま変えない。

**本文取得は別の軸。** `tools/fetch/` が持つ。Serper のように検索しか
持たない provider へ差し替えても、本文取得は独立して選べる。
"""

from functools import lru_cache

from config import get_settings
from tools.search.base import PageContent, SearchError, SearchProvider, SearchResult
from tools.search.serper import SerperProvider
from tools.search.tavily import TavilyProvider

_PROVIDERS: dict[str, type[SearchProvider]] = {
    "tavily": TavilyProvider,
    "serper": SerperProvider,
}


@lru_cache
def get_provider() -> SearchProvider:
    """プロセス内で使い回す provider。接続を毎回張り直さない。"""
    name = (get_settings().search_provider or "tavily").strip().lower()
    cls = _PROVIDERS.get(name)
    if cls is None:
        raise SearchError(
            f"SEARCH_PROVIDER の値が不正です: {name}（{'/'.join(sorted(_PROVIDERS))} のいずれか）"
        )
    return cls()


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
    "SerperProvider",
    "TavilyProvider",
    "close_provider",
    "get_provider",
]
