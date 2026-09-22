"""Tavily Extract を本文取得として使う。**現行の既定値。**

比較（#65）のための基準線。採用が決まるまで既定値を変えない。

`TavilyProvider` を自前で持つ。**検索 provider が何であっても本文取得を
Tavily にできる**ようにするため（Serper 検索 + Tavily Extract の比較用）。
"""

from __future__ import annotations

from tools.fetch.base import PageContent, PageFetcher
from tools.search.tavily import MAX_EXTRACT_URLS, TavilyProvider


class TavilyExtractFetcher(PageFetcher):
    name = "tavily"

    def __init__(self, provider: TavilyProvider | None = None) -> None:
        self._provider = provider or TavilyProvider()

    def fetch(self, urls: list[str]) -> tuple[list[PageContent], list[str]]:
        if not urls:
            return [], []

        # /extract は 21 件以上で HTTP 400。呼び出し側に上限を意識させず、
        # ここで分割する。**要求した URL は必ずどちらかに現れる。**
        pages: list[PageContent] = []
        failed: list[str] = []
        for i in range(0, len(urls), MAX_EXTRACT_URLS):
            got, missed = self._provider.extract(urls[i : i + MAX_EXTRACT_URLS])
            pages.extend(got)
            failed.extend(missed)
        return pages, failed

    def close(self) -> None:
        self._provider.close()
