"""Web Page Reader Tool。

URL からページ本文を取得する。用途は 2 つ。

  - Verification（#7）— 公式ページを再確認し、日時・締切・参加条件を検証する
  - 検索の抜粋では足りないときの本文取得

**検索結果の `content` で足りるなら、この Tool を呼ぶ必要はない。**
Tavily の検索は 800〜1500 文字の本文抜粋を返すため、多くの場合そちらで足りる。
本文全体が必要なときだけ使う。

取得した本文は **Untrusted Data**。`ToolResult(external=True)` で返す。
"""

from typing import Any

from ai import cost
from tools.base import PermissionLevel, Tool, ToolResult, registry
from tools.fetch import get_fetcher
from tools.search.base import PageContent
from tools.urlcheck import ALLOWED_SCHEMES, BLOCKED_HOSTS
from tools.urlcheck import has_valid_tld as _has_valid_tld
from tools.urlcheck import is_fetchable as _is_fetchable

# URL の判定は `tools/urlcheck.py` に集約した。取得経路が複数になったため、
# **経路ごとに書き直して 1 つ漏れる**のを避ける。
#
# 名前はここからも引ける形で残す。移設の前後で呼び出し側を書き換えずに済む。
_BLOCKED_HOSTS = BLOCKED_HOSTS

__all__ = [
    "ALLOWED_SCHEMES",
    "MAX_CONTENT_CHARS",
    "PageReaderTool",
    "_has_valid_tld",
    "_is_fetchable",
]

# 1 ページあたりの本文上限。実測で 43,910 文字のページがあった。
# これは安全側の歯止めで、LLM へ渡す量ではない（そちらは
# ai/schemas/extraction.MAX_PAGE_CONTENT_CHARS が別に絞る）。
MAX_CONTENT_CHARS = 50_000


class PageReaderTool(Tool):
    name = "read_page"
    description = "URL のページ本文を取得する"
    permission = PermissionLevel.AUTO

    def run(self, url: str | list[str], **_: Any) -> ToolResult:
        """1 件でも複数でも受ける。複数は 1 リクエストにまとめる。

        戻り値は `{"pages": [PageContent], "failed": [url]}`。
        **一部が失敗しても例外にしない。** 5 件中 1 件が落ちたときに
        残り 4 件を捨てるのは Agent の探索として不適切なため。
        """
        urls = [url] if isinstance(url, str) else list(url)
        # **検索 provider ではなく fetcher を使う。** 検索と本文取得は
        # 別々に選べる（Serper 検索 + Tavily Extract など）。
        fetcher = get_fetcher()

        # 取りに行けない URL は fetcher へ渡さず、失敗として返す。
        # 要求した URL は必ず pages か failed のどちらかに現れる。
        allowed, rejected = _split_by_scheme(urls)
        pages, failed = fetcher.fetch(allowed) if allowed else ([], [])
        # 本文取得の回数。検索とは分けて数える（#65）。
        # **試した数と取れた数を分ける。** 取れなかった分も使用量は発生する。
        if allowed:
            cost.record_extract(len(allowed))
            cost.record_extract_success(len(pages))

        # 外部から取得した内容。命令として扱わない。
        return ToolResult(
            {"pages": [_truncate(p) for p in pages], "failed": failed + rejected},
            external=True,
        )


registry.register(PageReaderTool())


def _split_by_scheme(urls: list[str]) -> tuple[list[str], list[str]]:
    """取りに行ってよい URL と、それ以外に分ける。"""
    allowed: list[str] = []
    rejected: list[str] = []
    for u in urls:
        (allowed if _is_fetchable(u) else rejected).append(u)
    return allowed, rejected


def _truncate(page: PageContent) -> PageContent:
    """本文が際限なく大きくならないようにする。"""
    if len(page.content) <= MAX_CONTENT_CHARS:
        return page
    return PageContent(url=page.url, title=page.title, content=page.content[:MAX_CONTENT_CHARS])
