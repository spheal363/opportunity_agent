"""本文取得（Page Fetcher）の共通インターフェース。

**検索 provider とは別に選ぶ。**

以前は Page Reader が `SearchProvider.extract()` を呼んでいた。Tavily が
検索と本文取得の両方を持つため、それで足りていた。

Serper は検索だけで、**本文は返さない**（title / link / snippet のみ）。
検索 provider を差し替えるだけでは本文不足は解決しないため、取得経路を
別の軸として切り出す。**Serper に extract を持つふりをさせない。**
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from tools.search.base import PageContent, SearchError


class FetchError(SearchError):
    """本文取得の失敗。

    `SearchError` を継承する。Agent Loop と Page Reader は既に
    `except SearchError` で拾っており、**取得経路を増やしたことで
    取りこぼしが生まれないようにする**ため。
    """


class PageFetcher(ABC):
    """URL からページ本文を取得する。

    `search()` を持たない。検索と本文取得は別々に選べる。
    """

    name: str

    @abstractmethod
    def fetch(self, urls: list[str]) -> tuple[list[PageContent], list[str]]:
        """戻り値は (取得できたもの, 取得できなかった URL)。

        **一部が失敗しても例外にしない。** 5 件中 1 件が落ちたときに
        残り 4 件を捨てるのは Agent の探索として不適切なため。

        要求した URL は必ずどちらかに現れる。
        """

    def close(self) -> None:
        """接続の後片付け。持たない実装は何もしなくてよい。"""
        return None


__all__ = ["FetchError", "PageContent", "PageFetcher"]
