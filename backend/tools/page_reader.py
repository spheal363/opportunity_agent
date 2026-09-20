"""Web Page Reader Tool。

URL からページ本文を取得する。用途は 2 つ。

  - Verification（#7）— 公式ページを再確認し、日時・締切・参加条件を検証する
  - 検索の抜粋では足りないときの本文取得

**検索結果の `content` で足りるなら、この Tool を呼ぶ必要はない。**
Tavily の検索は 800〜1500 文字の本文抜粋を返すため、多くの場合そちらで足りる。
本文全体が必要なときだけ使う。

取得した本文は **Untrusted Data**。`ToolResult(external=True)` で返す。
"""

import ipaddress
from typing import Any
from urllib.parse import urlparse

from tools.base import PermissionLevel, Tool, ToolResult, registry
from tools.search import get_provider
from tools.search.base import PageContent, SearchError

# http / https 以外は取りに行かない。file: や data: を Agent に踏ませない。
ALLOWED_SCHEMES = frozenset({"http", "https"})

# 取りに行かないホスト名。IP は ipaddress で別途判定する。
_BLOCKED_HOSTS = frozenset({"localhost", "localhost.localdomain", "metadata.google.internal"})

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
    """取りに行ってよい URL と、それ以外に分ける。"""
    allowed: list[str] = []
    rejected: list[str] = []
    for u in urls:
        (allowed if _is_fetchable(u) else rejected).append(u)
    return allowed, rejected


def _is_fetchable(url: str) -> bool:
    """取りに行ってよい URL か。

    Agent は LLM が読み取った URL を渡してくることがあり、その中身は
    ページの書き手が決められる。**内部アドレスを踏ませない。**

    現在の provider は取得を外部サービス側で行うためこのプロセスからの
    SSRF にはならないが、provider を自前の HTTP クライアントへ差し替えた
    時点で成立する。差し替えの可能性があるうちは手前で塞いでおく。

    **名前解決はしない。** 内部 IP へ解決されるホスト名は通る。
    完全な対策にはならず、明らかなものを落とすだけ。
    """
    try:
        parsed = urlparse(url)
    except ValueError:
        # 壊れた IPv6 表記（"http://[::1]./x" など）で urlparse 自体が投げる。
        # 1 件の壊れた URL で run 全体を落とさない。
        return False
    if parsed.scheme.lower() not in ALLOWED_SCHEMES:
        return False

    try:
        host = parsed.hostname
    except ValueError:
        return False
    if not host:
        return False
    host = host.rstrip(".").lower()
    if host in _BLOCKED_HOSTS:
        return False

    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # IP として解釈できないもの。**許可する形を決めて、それ以外を落とす。**
        #
        # 難読化した IP 表記（2130706433 / 0x7f000001 / 127.0x0.0.1 / 127.1）は
        # ipaddress では ValueError になるが OS の resolver は解釈する。
        # 表記を 1 つずつ潰すと必ず変種が漏れるため、**まっとうなホスト名の形**
        # だけを通す。実在する TLD は英字か punycode なので、末尾ラベルで判定できる。
        return _has_valid_tld(host)

    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local  # 169.254.169.254（クラウドのメタデータ）
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def _truncate(page: PageContent) -> PageContent:
    """本文が際限なく大きくならないようにする。"""
    if len(page.content) <= MAX_CONTENT_CHARS:
        return page
    return PageContent(url=page.url, title=page.title, content=page.content[:MAX_CONTENT_CHARS])


def _has_valid_tld(host: str) -> bool:
    """まっとうなホスト名の形か。

    末尾ラベルが英字 2 文字以上（`com` / `jp`）か punycode（`xn--...`）の
    ときだけ通す。数字や `0x` を含む末尾ラベルは実在の TLD に無いため、
    難読化した IP 表記をここでまとめて落とせる。

      2130706433    -> 末尾 "2130706433"  落とす
      0x7f000001    -> 末尾 "0x7f000001"  落とす
      127.0x0.0.1   -> 末尾 "1"           落とす
      127.1         -> 末尾 "1"           落とす
      connpass.com  -> 末尾 "com"         通す
    """
    labels = [lb for lb in host.split(".") if lb]
    if len(labels) < 2:
        return False  # 単一ラベル。内部ホスト名の可能性がある
    tld = labels[-1]
    if tld.startswith("xn--"):
        return len(tld) > 4
    return len(tld) >= 2 and tld.isalpha()
