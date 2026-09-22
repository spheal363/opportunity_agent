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


# --- 一覧の「候補」かどうかの門 --------------------------------------------


def test_a_repeated_shape_makes_it_a_candidate():
    assert listing.may_be_listing(LISTING_BODY, base_url=BASE) is True


def test_an_empty_body_is_not_a_candidate():
    assert listing.may_be_listing("", base_url=BASE) is False


def test_a_page_with_few_links_is_not_a_candidate():
    assert listing.may_be_listing(INDIVIDUAL_BODY, base_url=BASE + "/2001001") is False


def test_the_structure_alone_does_not_decide_listing_or_article():
    """**構造だけでは分けられない（実測）。**

        clubberia.com/ja/events/         同形 27 / 題名に日付 100%
        okinawatimes.co.jp/articles/-/…  同形 24 / 題名に日付  67%

    どちらも門は通る。一覧か記事かは本文を読んで LLM が判断する。
    以前の「自分と同じ形のリンクが並ぶページは記事」は、
    **イベント一覧にも同じ形の個別リンクが並ぶ**ので使えなかった。
    """
    article_url = "https://www.okinawatimes.co.jp/articles/-/1863932"
    article = "\n".join(
        f"[記事{i}](https://www.okinawatimes.co.jp/articles/-/19{i:05d})" for i in range(20)
    )
    listing_url = "https://clubberia.com/ja/events/"
    events = "\n".join(
        f"[Event {i} 9.{i:02d} TUE](https://clubberia.com/ja/events/3093{i:02d})" for i in range(20)
    )
    assert listing.may_be_listing(article, base_url=article_url) is True
    assert listing.may_be_listing(events, base_url=listing_url) is True


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


# --- 絞り込みリンクを子と間違えない（#47）----------------------------------


def test_same_page_filters_are_not_children():
    """**実測で、絞り込みリンクがイベント本体より数で勝った。**

    `housemusiclovers.net/events/` の「今日 / 明日 / 今週末 / 来月 …」は
    すべて `/events/?hmls_date=…` で、パスが同じ。**自分と同じパスは子ではない。**
    """
    base = "https://housemusiclovers.net/events/"
    body = "\n".join(
        [f"[{w}]({base}?hmls_date={w})" for w in ("today", "tomorrow", "weekend", "month")]
        + [f"[Event {i}](https://housemusiclovers.net/events/party-{i})" for i in range(3)]
    )
    picked = listing.same_shape_links(listing.extract_links(body, base_url=base), base_url=base)

    assert picked, "子リンクが 1 つも残っていない"
    assert all("hmls_date" not in link.url for link in picked)


def test_the_query_key_is_part_of_the_shape():
    """クエリを無視すると、別々の絞り込みが同じ形に潰れる。"""
    a = listing._path_shape("https://x/events/?date=today")
    b = listing._path_shape("https://x/events/?view=calendar")
    assert a != b


def test_links_of_other_shapes_are_still_offered():
    """**形で切り捨てない。** 1 ページに数件しか載らない一覧を落とさない。"""
    base = "https://x/events/"
    body = "\n".join(
        [f"[A{i}](https://x/events/a-{i})" for i in range(8)] + ["[B](https://x/special/one)"]
    )
    urls = {
        link.url
        for link in listing.same_shape_links(
            listing.extract_links(body, base_url=base), base_url=base
        )
    }
    assert "https://x/special/one" in urls


def test_the_number_of_links_offered_is_capped():
    base = "https://x/events/"
    body = "\n".join(f"[E{i}](https://x/events/e-{i})" for i in range(100))
    picked = listing.same_shape_links(listing.extract_links(body, base_url=base), base_url=base)
    assert len(picked) == listing.MAX_LINKS_OFFERED
