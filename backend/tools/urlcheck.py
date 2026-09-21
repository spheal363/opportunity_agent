"""取りに行ってよい URL かの判定。

**Search Provider と Page Fetcher の両方から使う。**

以前は `tools/page_reader.py` の中にあった。本文取得を検索 provider から
切り離した（#65）ことで、取得経路が複数になった。**経路を増やすたびに
保護を書き直すと、どれか 1 つが漏れる。** 判定はここ 1 か所に置く。
"""

from __future__ import annotations

import ipaddress
from urllib.parse import urlparse

# http / https 以外は取りに行かない。file: や data: を Agent に踏ませない。
ALLOWED_SCHEMES = frozenset({"http", "https"})

# 取りに行かないホスト名。IP は ipaddress で別途判定する。
BLOCKED_HOSTS = frozenset({"localhost", "localhost.localdomain", "metadata.google.internal"})


# URL に入っていてはいけない文字。
#
# **ここで落とすのが根本。** 制御文字を含む URL を通すと、それを
# パスに埋める取得経路（Jina Reader）で `httpx.InvalidURL` が飛び、
# **1 件の不正な URL で他の候補まで巻き添えになる。**
#
# URL は LLM がページ本文から読み取った値で、**ページの書き手が
# 仕込める。** 取得経路が増えても効くよう、判定の側で落とす。
_FORBIDDEN = frozenset({chr(c) for c in range(0x21)} | {chr(0x7F)})


def is_fetchable(url: str) -> bool:
    """取りに行ってよい URL か。

    Agent は LLM が読み取った URL を渡してくることがあり、その中身は
    ページの書き手が決められる。**内部アドレスを踏ませない。**

    Tavily Extract は取得を外部サービス側で行うためこのプロセスからの
    SSRF にはならないが、**自前 HTTP 取得へ差し替えた時点で成立する。**
    Jina Reader も URL を渡す先が別サービスというだけで、こちらが
    内部アドレスを渡してよい理由にはならない。手前で塞いでおく。

    **名前解決はしない。** 内部 IP へ解決されるホスト名は通る。
    完全な対策にはならず、明らかなものを落とすだけ。
    """
    if any(c in _FORBIDDEN for c in url):
        # 制御文字・空白。まっとうな URL には現れない。
        return False

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
    if host in BLOCKED_HOSTS:
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
        return has_valid_tld(host)

    return not (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local  # 169.254.169.254（クラウドのメタデータ）
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def has_valid_tld(host: str) -> bool:
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
