"""希望した地域と開催地の照合（#47）。保存済みの値だけで判定する。"""

import pytest

from ai import region as r


def _c(wanted, location, fmt):
    return r.classify(wanted=wanted, location=location, opportunity_format=fmt)


TOKYO = "東京 / オンライン"


# --- 実測で起きたこと -------------------------------------------------------


def test_the_okinawa_workshop_is_not_a_match():
    """**実測で、希望が「東京 / オンライン」なのに沖縄の現地開催が推薦された。**

    会場名に「東京」が出てこない現地開催は、一致とは言えない。
    """
    got = _c(TOKYO, "生涯学習・文化振興センターゆらてく（研修室3）", "offline")
    assert got is r.RegionMatch.MISMATCH


def test_the_mismatch_note_does_not_claim_a_prefecture():
    """**「沖縄だ」と断定しない。** 言えるのは「希望地を確認できない」こと。"""
    note = r.note(r.RegionMatch.MISMATCH, wanted=TOKYO, location="ゆらてく")
    assert "確認できません" in note
    assert "沖縄" not in note


# --- 一致 -------------------------------------------------------------------


def test_a_tokyo_venue_matches():
    assert _c(TOKYO, "東京マリオットホテル（品川）", "offline") is r.RegionMatch.MATCH


def test_an_online_event_matches_when_online_is_wanted():
    assert _c(TOKYO, None, "online") is r.RegionMatch.MATCH


def test_a_hybrid_event_matches_when_online_is_wanted():
    assert _c(TOKYO, "大阪", "hybrid") is r.RegionMatch.MATCH


def test_an_online_only_event_is_out_when_only_a_place_is_wanted():
    """**オンラインのみは現地参加できない。**

    希望が「東京」だけ（オンラインを含まない）なら対象外と言い切れる。
    """
    assert _c("東京", None, "online") is r.RegionMatch.MISMATCH


def test_a_multi_site_event_including_tokyo_matches():
    assert _c(TOKYO, "全国4拠点 (東京, 大阪, 福岡, 札幌)", "offline") is r.RegionMatch.MATCH


# --- 未確認は一致にしない ---------------------------------------------------


def test_an_offline_event_without_a_venue_is_unknown():
    """**現地開催だが場所が取れていない。東京と決めつけない。**"""
    assert _c(TOKYO, None, "offline") is r.RegionMatch.UNKNOWN


def test_an_event_without_a_format_or_a_matching_place_is_unknown():
    assert _c(TOKYO, None, None) is r.RegionMatch.UNKNOWN


def test_unknown_is_never_reported_as_a_match():
    note = r.note(r.RegionMatch.UNKNOWN, wanted=TOKYO, location=None)
    assert "未確認" in note


def test_no_wanted_region_means_no_judgement():
    """希望が未記入なら判定しない。**全件を不一致にしない。**"""
    assert _c(None, "沖縄", "offline") is r.RegionMatch.UNKNOWN
    assert _c("", "沖縄", "offline") is r.RegionMatch.UNKNOWN


# --- 判断の根拠にしないもの -------------------------------------------------


def test_the_domain_is_not_used_to_decide_the_place():
    """**`dtm.okinawa` だから沖縄、とは判断しない。** URL は開催地ではない。

    渡すのは `location` と `format` だけで、URL は引数に無い。
    """
    import inspect

    assert "url" not in inspect.signature(r.classify).parameters


def test_the_word_streaming_alone_does_not_make_it_online():
    """**「配信」という語だけでオンライン参加可能と判断しない。**

    見るのは抽出済みの `format`。説明文の語は拾わない。
    """
    assert _c(TOKYO, "大阪ホール（配信あり）", "offline") is r.RegionMatch.MISMATCH


def test_eligibility_is_not_mixed_into_the_region():
    """参加資格は別。地域の判定に持ち込まない。"""
    import inspect

    assert "eligibility" not in inspect.signature(r.classify).parameters


# --- 希望の書き方 -----------------------------------------------------------


@pytest.mark.parametrize(
    "wanted", ["東京 / オンライン", "東京、オンライン", "東京・オンライン", "東京/online"]
)
def test_separators(wanted):
    places, online = r.wanted_places(wanted)
    assert places == ["東京"] and online is True


# --- 実測の誤りを繰り返さない（#47）----------------------------------------


def test_a_hybrid_event_in_the_wanted_place_matches():
    """**実測で、hybrid を無条件に不一致にしていた。**

    `AI HACK 2026`（東京都23区某所・hybrid）が mismatch になった。
    現地参加もできるので、会場と都道府県で見る。
    """
    got = r.classify(
        wanted="東京", location="東京都23区某所", opportunity_format="hybrid", region="東京都"
    )
    assert got is r.RegionMatch.MATCH


def test_a_romaji_venue_matches_through_the_prefecture():
    """**実測で `ZEROTOKYO` が「東京」に一致しなかった。**

    会場名はローマ字・地名のみのことがある。抽出した都道府県で照合する。
    """
    assert (
        r.classify(
            wanted="東京", location="ZEROTOKYO", opportunity_format="offline", region="東京都"
        )
        is r.RegionMatch.MATCH
    )
    assert (
        r.classify(
            wanted="東京",
            location="ヨドバシHD池袋ビル9階屋上",
            opportunity_format="offline",
            region="東京都",
        )
        is r.RegionMatch.MATCH
    )


def test_the_prefecture_outranks_the_venue_name():
    """都道府県が分かっているなら、会場名より優先する。"""
    got = r.classify(
        wanted="東京", location="読谷村立図書館", opportunity_format="offline", region="沖縄県"
    )
    assert got is r.RegionMatch.MISMATCH


def test_online_participation_overrides_the_format():
    """**配信のみは参加ではない。** `format` より抽出した可否を優先する。"""
    watched_only = r.classify(
        wanted="東京 / オンライン",
        location="大阪",
        opportunity_format="hybrid",
        region="大阪府",
        online_participation=False,
    )
    assert watched_only is r.RegionMatch.MISMATCH
