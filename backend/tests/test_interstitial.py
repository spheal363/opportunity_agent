"""アクセス確認・エラーページの判定（#47）。保存済みデータで回帰を見る。"""

from ai import interstitial
from ai.extraction import extract_many
from tools.search.base import SearchResult


def _check(title, content):
    return interstitial.looks_like_interstitial(title=title, content=content)


# --- 実測で候補一覧に並んだもの -------------------------------------------


def test_the_cloudflare_page_that_reached_the_list_is_caught():
    """**実測で `Just a moment...` が Opportunity として保存された。**

    本文が空なので日時も締切も取れず、「日程未確認の候補」として並んだ。
    """
    assert _check("Just a moment...", "") is not None


def test_the_reason_is_recorded_not_just_a_boolean():
    """落とした理由を残す。**黙って消さない。**"""
    reason = _check("Just a moment...", "")
    assert "just a moment" in reason and "本文" in reason


# --- タイトルの一語だけに依存しない ---------------------------------------


def test_a_real_page_quoting_the_phrase_is_kept():
    """**定型文に一致しただけでは落とさない。**

    Prompt Injection やボット対策の解説記事が文面を引用していることがある。
    本文があるページは取得できている。
    """
    body = "Cloudflare の Just a moment... 画面を突破する方法を解説します。" + "本文" * 200
    assert _check("ボット対策の仕組み", body) is None


def test_a_short_but_real_page_is_kept():
    """**短いだけでは落とさない。** 素っ気ない告知ページはある。"""
    assert _check("AI ハッカソン 参加者募集", "10月10日 渋谷で開催。参加無料。") is None


def test_full_width_text_is_caught():
    """全角で書かれていても拾う。"""
    assert _check("Ｊｕｓｔ　ａ　ｍｏｍｅｎｔ．．．", "") is not None


def test_error_pages_are_caught():
    for title in ("403 Forbidden", "404 Not Found", "ページが見つかりません"):
        assert _check(title, "") is not None, title


def test_javascript_notice_is_caught():
    assert _check("お知らせ", "Please enable JavaScript to continue.") is not None


def test_an_ordinary_event_is_not_caught():
    assert _check("DTM 作曲ワークショップ 参加者募集", "初心者向け。" * 60) is None


# --- 抽出の経路 ------------------------------------------------------------


def test_extraction_skips_it_and_keeps_the_others(monkeypatch):
    """**1 件落としても他の候補は続ける。**"""
    from ai import extraction

    seen: list[str] = []

    monkeypatch.setattr(
        extraction,
        "extract_opportunity",
        lambda url, content, **k: (seen.append(url), _stub())[1],
    )
    results = [
        SearchResult(title="Just a moment...", url="https://x/blocked", snippet="", content=""),
        SearchResult(
            title="AI ハッカソン",
            url="https://x/ok",
            snippet="s",
            content="10月10日 渋谷で開催。" * 30,
        ),
    ]
    done, failed = extract_many(results)

    assert seen == ["https://x/ok"], "アクセス確認ページを抽出に回している"
    assert [u for u, _ in done] == ["https://x/ok"]


def _stub():
    from ai.schemas.extraction import ExtractedOpportunity

    return ExtractedOpportunity(title="t", type="hackathon")
