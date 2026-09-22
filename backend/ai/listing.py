"""イベント一覧ページから、個別イベントのリンクを取り出す（#47）。

実測で、音楽方向の検索結果 5 件は**一覧 4 件と記事 1 件で、個別イベントが
0 件**だった。粗選別は「参加・応募できる機会か」で判定するので一覧を落とし、
読まれたのは記事 1 件だけ。**一覧の先にある個別イベントへ到達できていない。**

    検索 -> 一覧ページ -> ここでリンクを取り出す -> 有望なものだけ取得 -> 抽出

## URL を作らない

**取り出すのは本文に実在するリンクだけ。** `?p=6533` の隣は `?p=6534` だろう、
のような推測をしない。日付や開催地も、リンク先の本文を読むまで埋めない。

## URL の形だけで分類しない

実測で、`ja.ra.co/events/jp/tokyo/house` を「個別イベント」と誤分類した
（実際は一覧）。逆に `timeout.jp/tokyo/ja/music/music-festivals-in-...` は
記事だが個別に見える。**URL とタイトルの形だけでは決まらない。**

ここでは本文の構造（同じ形のリンクがいくつ並ぶか）を手がかりにし、
判断がつかないものは `UNKNOWN` にする。**捨てずに不明として残す。**
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

# Jina Reader が返す Markdown のリンク。`[題名](URL)`。
# 画像リンク `[![...](img)](url)` にも当たるので、題名側の画像記法は後で削る。
_MD_LINK = re.compile(r"\[([^\]]{0,200}?)\]\((https?://[^\s)]+)\)")
# 題名に残る画像記法。`![Image 3: 実際の題名](https://...)`
_IMAGE = re.compile(r"!\[(?:Image \d+:\s*)?([^\]]*)\]\([^)]*\)")

# リンク先として明らかに機会ではないもの。**ここで落とすのは導線だけ。**
_NAVIGATION = (
    "/login",
    "/signin",
    "/signup",
    "/register?",
    "/account",
    "/privacy",
    "/terms",
    "/about",
    "/contact",
    "/faq",
    "/help",
    "/search",
    "/tag/",
    "/tags/",
    "/category/",
    "/categories/",
    "/feed",
    "/rss",
    "/sitemap",
    "/app",
    "/download",
)
_SOCIAL = (
    "twitter.com",
    "x.com",
    "facebook.com",
    "instagram.com",
    "youtube.com",
    "line.me",
    "tiktok.com",
    "apple.com",
    "play.google.com",
)

# 一覧と見なすための、同じ深さのリンクの数。**仮説であって正解ではない。**
LISTING_MIN_LINKS = 6
# LLM へ見せるリンクの上限。**プロンプトが膨らみすぎないように。**
MAX_LINKS_OFFERED = 40


@dataclass(frozen=True)
class Link:
    """本文に実在した 1 本のリンク。**URL は本文から取ったものだけ。**"""

    title: str
    url: str


def _clean_title(raw: str) -> str:
    return _IMAGE.sub(r"\1", raw).strip()


def _flatten_images(content: str) -> str:
    """画像記法を alt テキストへ潰す。

    一覧は `[![Image 1: flyer](img.jpg)](/events/1)` の形が多く、
    そのままだとリンクの題名に画像記法が残る（実測）。
    """
    return _IMAGE.sub(r"\1", content or "")


def _is_navigation(url: str) -> bool:
    lowered = url.lower()
    if any(s in lowered for s in _SOCIAL):
        return True
    path = urlparse(lowered).path or "/"
    return any(n in path for n in _NAVIGATION)


def extract_links(content: str, *, base_url: str, same_host_only: bool = True) -> list[Link]:
    """本文に実在するリンクを取り出す。**組み立てない。**

    同じホストのものだけを既定で返す。一覧サイトの外部リンクは広告や
    別サービスのことが多く、探索元としての手がかりにならない。
    """
    host = urlparse(base_url).netloc.lower()
    seen: set[str] = set()
    out: list[Link] = []
    for match in _MD_LINK.finditer(_flatten_images(content)):
        title = _clean_title(match.group(1))
        url = urljoin(base_url, match.group(2)).split("#")[0].rstrip("/")
        if not url or url in seen:
            continue
        if same_host_only and urlparse(url).netloc.lower() != host:
            continue
        if url.rstrip("/") == base_url.rstrip("/") or _is_navigation(url):
            continue
        seen.add(url)
        out.append(Link(title=title, url=url))
    return out


def _path_shape(url: str) -> str:
    """URL の「形」。数字と ID を伏せて比べる。

    `/events/123` と `/events/456` は同じ形。一覧に同じ形のリンクが
    たくさん並ぶことを手がかりにする。

    **クエリの鍵も形に含める。** 含めないと、絞り込みリンク
    （`/events/?hmls_date=today`, `?hmls_date=tomorrow` …）が
    すべて `/events/` に潰れ、**イベント本体より数で勝ってしまう**（実測）。
    """
    parsed = urlparse(url)
    shape = re.sub(r"\d+", "#", parsed.path or "/")
    keys = sorted({kv.split("=")[0] for kv in parsed.query.split("&") if kv})
    return f"{shape}?{','.join(keys)}" if keys else shape


def may_be_listing(content: str, *, base_url: str, links: list[Link] | None = None) -> bool:
    """**一覧の「候補」かどうかだけを構造で見る。判定はしない。**

    ここで返すのは「同じ形のリンクが並んでいる」という事実だけ。
    一覧か記事かは本文を読まないと分からない（`ai/explore.py` が LLM に聞く）。

    **構造だけでは分けられないことを実測した。**

        clubberia.com/ja/events/            同形 27 / 題名に日付 100%
        okinawatimes.co.jp/articles/-/…     同形 24 / 題名に日付  67%

    以前は「自分と同じ形のリンクが並ぶページは記事」としていたが、
    **イベント一覧にも同じ形の個別リンクが並ぶ**ので使えない。
    構造は「LLM に聞く価値があるか」の門にとどめる。
    """
    body = content or ""
    if not body.strip():
        return False
    found = links if links is not None else extract_links(body, base_url=base_url)
    if len(found) < LISTING_MIN_LINKS:
        return False
    shapes: dict[str, int] = {}
    for link in found:
        shape = _path_shape(link.url)
        shapes[shape] = shapes.get(shape, 0) + 1
    return max(shapes.values()) >= LISTING_MIN_LINKS


def same_shape_links(
    links: list[Link], *, base_url: str | None = None, limit: int | None = None
) -> list[Link]:
    """一覧の中で**いちばん多い形**のリンクだけを返す。

    ヘッダやサイドバーの雑多なリンクを外し、並んでいるイベントの列を取る。

    **同じページの絞り込みは外す。** 実測で、`housemusiclovers.net/events/` の
    「今日 / 明日 / 今週末 / 来月 …」がイベント本体より数で勝ち、
    選ぶ相手がフィルタだけになった。**自分と同じパスのリンクは子ではない。**
    """
    if not links:
        return []
    base_path = re.sub(r"\d+", "#", urlparse(base_url).path or "/") if base_url else None
    shapes: dict[str, list[Link]] = {}
    for link in links:
        if base_path is not None:
            path = re.sub(r"\d+", "#", urlparse(link.url).path or "/")
            if path.rstrip("/") == base_path.rstrip("/"):
                continue
        shapes.setdefault(_path_shape(link.url), []).append(link)
    if not shapes:
        return []
    # **いちばん多い形を先頭に置き、残りも渡す。** 形で切り捨てると、
    # 1 ページに数件しか載らない一覧のイベントを丸ごと落とす（実測）。
    # どれを読むかは本文を見た LLM が選ぶ。
    ordered = sorted(shapes.values(), key=len, reverse=True)
    out = [link for group in ordered for link in group]
    return out[: limit or MAX_LINKS_OFFERED]
