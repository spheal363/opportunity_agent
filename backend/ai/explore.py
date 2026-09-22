"""一覧ページを「探索元」として使い、個別イベントまで進む（#47）。

    一覧ページの本文 -> 実在するリンクを取り出す -> 希望に合いそうなものを選ぶ
                    -> そのページを取得 -> 抽出へ回す

実測で、音楽方向の検索結果は**一覧 4 件と記事 1 件で個別イベントが 0 件**
だった。ここが無いと、一覧の先にあるイベントへ永遠に届かない。

## 上限は設定で変える

**最初の実験条件であって、製品として最適と決まった値ではない。**
`config.py` の `LISTING_*` で変えられる。実測してから調整する。

## 取れなかったことを記録する

取得失敗・アクセス確認ページ・リンク 0 件は、いずれも理由を残す。
**アクセス制限は回避しない。**
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace

from ai import cost, guard, interstitial, listing
from ai.llm import LLMError, generate_structured
from ai.prompts import link_pick as prompt
from ai.routing import Step
from ai.schemas.link_pick import LinkPickOutput
from logging_config import get_logger
from tools.search.base import PageContent

logger = get_logger(__name__)


@dataclass
class ExploreResult:
    """一覧 1 ページを辿った結果。**数えるのは個別イベント。**"""

    # 取得できた個別イベントのページ
    pages: list[PageContent] = field(default_factory=list)
    # 一覧から取り出せたリンクの数（選ぶ前）
    links_found: int = 0
    # 選んだ数
    picked: int = 0
    # このページはイベント一覧だったか（LLM の判断）
    is_listing: bool = False
    # 取れなかったものと理由。**隠さない。**
    failures: list[tuple[str, str]] = field(default_factory=list)


def links_from(page: PageContent) -> list[listing.Link]:
    """一覧ページの本文から、実在するリンクだけを取り出す。"""
    found = listing.extract_links(page.content, base_url=page.url)
    return listing.same_shape_links(found, base_url=page.url)


EXCERPT_CHARS = 1500


def pick_links(
    links: list[listing.Link],
    *,
    wishes: list[str],
    location: str | None,
    window: str | None,
    limit: int,
    excerpt: str = "",
) -> tuple[bool, list[listing.Link]]:
    """どのリンクを読むかを選ぶ。**番号で選ばせ、URL は作らせない。**

    失敗したら空を返す。**上位から機械的に取る代替はしない**
    （一覧の並び順は開催日順とは限らず、古い回が先頭のこともある）。
    """
    if not links:
        return False, []
    with cost.step("link_pick"):
        try:
            out = generate_structured(
                schema=LinkPickOutput,
                system=prompt.SYSTEM,
                user=prompt.build_user(
                    wishes=wishes,
                    location=location,
                    window=window,
                    links=links,
                    limit=limit,
                    excerpt=excerpt,
                ),
                step=Step.LINK_PICK,
            ).data
        except LLMError as exc:
            logger.warning("explore.pick_failed reason=%s", exc)
            return False, []

    if not out.is_listing:
        # **一覧ではない。** 記事の関連記事欄にリンクが並んでいただけ。
        logger.info("explore.not_a_listing reason=%s", out.listing_reason[:80])
        return False, []

    picked: list[listing.Link] = []
    seen: set[int] = set()
    for item in out.picked:
        # **渡していない番号は捨てる。** 作られた index で落ちない。
        if item.index < 0 or item.index >= len(links) or item.index in seen:
            continue
        seen.add(item.index)
        picked.append(links[item.index])
        if len(picked) >= limit:
            break
    return True, picked


def follow(
    page: PageContent,
    *,
    wishes: list[str],
    location: str | None,
    window: str | None,
    limit: int,
    fetch: object,
) -> ExploreResult:
    """一覧 1 ページから、個別イベントのページまで進む。

    `fetch` は URL の一覧を受け取り `PageContent` を返す呼び出し
    （`tools.registry` の `read_page` を包んだもの）。
    """
    result = ExploreResult()
    links = links_from(page)
    result.links_found = len(links)
    if not links:
        result.failures.append((page.url, "本文から個別イベントのリンクを取り出せませんでした"))
        return result

    is_listing, chosen = pick_links(
        links,
        wishes=wishes,
        location=location,
        window=window,
        limit=limit,
        excerpt=(page.content or "")[:EXCERPT_CHARS],
    )
    result.is_listing = is_listing
    result.picked = len(chosen)
    if not is_listing:
        # **記事の関連記事欄にリンクが並んでいただけ。** 一覧ではない。
        result.failures.append((page.url, "イベント一覧ではありませんでした"))
        return result
    if not chosen:
        result.failures.append((page.url, "希望に合いそうなリンクを選べませんでした"))
        return result

    fetched = fetch([link.url for link in chosen])  # type: ignore[operator]
    got = {p.url: p for p in fetched}
    for link in chosen:
        got_page = got.get(link.url)
        if got_page is None:
            result.failures.append((link.url, "本文を取得できませんでした"))
            continue
        why = interstitial.looks_like_interstitial(title=got_page.title, content=got_page.content)
        if why is not None:
            # **アクセス制限は回避しない。** 記録して次へ。
            result.failures.append((link.url, f"取得できませんでした（{why}）"))
            continue
        checked = guard.inspect(got_page.content)
        result.pages.append(replace(got_page, content=checked.text))
    return result
