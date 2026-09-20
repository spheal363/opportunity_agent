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
from urllib.parse import urlparse

from tools.base import PermissionLevel, Tool, ToolResult, registry
from tools.search import get_provider
from tools.search.base import PageContent, SearchError

# http / https 以外は取りに行かない。file: や data: を Agent に踏ませない。
ALLOWED_SCHEMES = frozenset({"http", "https"})

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
        provider = get_provider()
        if not provider.supports_extract:
            raise SearchError(f"{provider.name} はページ取得に対応していません")

        # 取りに行けない URL は provider へ渡さず、失敗として返す。
        # 要求した URL は必ず pages か failed のどちらかに現れる。
        allowed, rejected = _split_by_scheme(urls)
        pages, failed = provider.extract(allowed) if allowed else ([], [])

        # 外部から取得した内容。命令として扱わない。
        return ToolResult(
            {"pages": [_truncate(p) for p in pages], "failed": failed + rejected},
            external=True,
        )


registry.register(PageReaderTool())


def _split_by_scheme(urls: list[str]) -> tuple[list[str], list[str]]:
    """http / https のものと、それ以外に分ける。"""
    allowed: list[str] = []
    rejected: list[str] = []
    for u in urls:
        scheme = urlparse(u).scheme.lower()
        (allowed if scheme in ALLOWED_SCHEMES else rejected).append(u)
    return allowed, rejected


def _truncate(page: PageContent) -> PageContent:
    """本文が際限なく大きくならないようにする。"""
    if len(page.content) <= MAX_CONTENT_CHARS:
        return page
    return PageContent(url=page.url, title=page.title, content=page.content[:MAX_CONTENT_CHARS])
