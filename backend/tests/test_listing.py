"""一覧ページからの個別リンク取り出し（#47）。ネットワークへは出ない。"""

from ai import listing

BASE = "https://ja.ra.co/events/jp/tokyo/house"

# 一覧ページの本文（Jina Reader が返す Markdown の形）。
LISTING_BODY = """
# 東京 でこれから開催される House イベント

[![Image 1: flyer](https://ja.ra.co/img/1.jpg)](https://ja.ra.co/events/2001001)
[Warehouse Session](https://ja.ra.co/events/2001001)
[Deep House Night](https://ja.ra.co/events/2001002)
[Techno Bunker](https://ja.ra.co/events/2001003)
[Sunset Terrace](https://ja.ra.co/events/2001004)
[Basement Groove](https://ja.ra.co/events/2001005)
[Midnight Rotation](https://ja.ra.co/events/2001006)
[ログイン](https://ja.ra.co/login)
[プライバシーポリシー](https://ja.ra.co/privacy)
[Twitter](https://twitter.com/ra)
"""

INDIVIDUAL_BODY = """
# Warehouse Session
日付 2026年10月10日 / 会場 Contact Tokyo / 料金 ¥3000
[チケット](https://ja.ra.co/tickets/2001001)
"""


# --- リンクの取り出し -------------------------------------------------------


def test_links_come_from_the_body_only():
    """**URL を組み立てない。** 本文にあるものだけ。"""
    links = listing.extract_links(LISTING_BODY, base_url=BASE)
    urls = {link.url for link in links}

    assert "https://ja.ra.co/events/2001001" in urls
    # 隣の番号を勝手に作らない
    assert "https://ja.ra.co/events/2001007" not in urls


def test_navigation_and_social_are_dropped():
    urls = {link.url for link in listing.extract_links(LISTING_BODY, base_url=BASE)}
    assert not any("/login" in u or "/privacy" in u or "twitter" in u for u in urls)


def test_the_image_markup_is_stripped_from_the_title():
    links = listing.extract_links(LISTING_BODY, base_url=BASE)
    assert all("![" not in link.title for link in links)


def test_the_same_url_is_not_returned_twice():
    """画像リンクと文字リンクが同じ先を指すことがある。"""
    links = listing.extract_links(LISTING_BODY, base_url=BASE)
    assert len({link.url for link in links}) == len(links)


def test_other_hosts_are_not_followed_by_default():
    body = "[外部](https://example.com/events/1)\n" + LISTING_BODY
    urls = {link.url for link in listing.extract_links(body, base_url=BASE)}
    assert not any("example.com" in u for u in urls)


# --- 種類の見立て -----------------------------------------------------------


def test_a_listing_is_recognised_by_the_repeated_shape():
    assert listing.classify_page(LISTING_BODY, base_url=BASE) is listing.PageKind.LISTING


def test_an_individual_page_is_not_called_a_listing():
    """**一覧でないと判断できれば十分。** 断定しない。"""
    kind = listing.classify_page(INDIVIDUAL_BODY, base_url="https://ja.ra.co/events/2001001")
    assert kind is not listing.PageKind.LISTING


def test_an_empty_body_is_unknown():
    assert listing.classify_page("", base_url=BASE) is listing.PageKind.UNKNOWN


def test_the_url_shape_alone_does_not_decide():
    """**実測で URL の形だけの分類が外れた。**

    `ja.ra.co/events/jp/tokyo/house` は一覧、
    `timeout.jp/tokyo/ja/music/music-festivals-in-...` は記事だが
    どちらも「深いパス」で、形だけでは区別できない。
    """
    article = "# 音楽フェス5選\n本文がここに続く。" * 5
    kind = listing.classify_page(article, base_url="https://www.timeout.jp/tokyo/ja/music/x")
    assert kind is not listing.PageKind.LISTING


# --- 並んでいる列だけ取る ---------------------------------------------------


def test_only_the_repeated_column_is_returned():
    links = listing.extract_links(LISTING_BODY, base_url=BASE)
    picked = listing.same_shape_links(links)

    assert len(picked) == 6
    assert all("/events/200100" in link.url for link in picked)


def test_the_limit_is_respected():
    links = listing.extract_links(LISTING_BODY, base_url=BASE)
    assert len(listing.same_shape_links(links, limit=2)) == 2


# --- 粗選別が探索元を落とさない（#47）--------------------------------------


def test_the_prefilter_question_counts_a_listing_as_an_opportunity():
    """**実測で、一覧 4 件が粗選別で落ちて記事 1 件だけが読まれた。**

    「参加・応募できる機会か」だけを聞くと、一覧はどちらでもないので
    低く出る。**個別イベントでないことと、価値が無いことを分ける。**
    """
    from ai.jev import questions as q

    assert "イベント一覧" in q.IS_OPPORTUNITY
    assert "個別の開催へたどれる" in q.IS_OPPORTUNITY
    # 記事は従来どおり該当しない。
    assert "解説記事" in q.IS_OPPORTUNITY
