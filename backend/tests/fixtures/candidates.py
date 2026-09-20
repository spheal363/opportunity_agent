"""比較（#65）用の固定データ。

**検索の抜粋から始める。** 抽出済みの DB 行だけで比べると、抽出そのものの
差が見えなくなる。実際の入口は検索結果なので、そこから揃える。

取得日時も固定する。「いま」が動くと、受付中か終了かの判定が日によって
変わり、比較にならない。

含めているもの:

  締切切れ            deadline が過ぎている
  開催終了            end_at が過ぎている（種類によって判定が変わる）
  受付中              締切が先
  日時が不明          抜粋にも本文にも日付が無い
  重複                同じ催しが別 URL で 2 件
  取得失敗            本文が取れない
  意外だが関連する    本人が検索しない領域だが目標につながる
  記事                参加できる機会ではない（解説記事）
"""

from __future__ import annotations

from datetime import UTC, datetime

from tools.search.base import PageContent, SearchResult

# 比較のための「いま」。**動かさない。**
NOW = datetime(2026, 9, 20, 12, 0, tzinfo=UTC)

GOAL_SUMMARY = "AI Agent を作れるエンジニアになり、将来は自分で事業を立ち上げたい"
INTERESTS = ["AI Agent", "プロダクト開発", "音楽", "DJ", "起業"]


def _r(
    title: str, url: str, snippet: str, content: str | None = None, score: float | None = None
) -> SearchResult:
    return SearchResult(title=title, url=url, snippet=snippet, content=content, score=score)


# --- Tavily 相当（本文抜粋つき）-------------------------------------------
# 検索結果に 800〜1500 文字の本文抜粋が載る想定。ここでは短く畳んである。
TAVILY_RESULTS: list[SearchResult] = [
    _r(
        "AI Agent Hackathon 2026 参加者募集",
        "https://example-hack.jp/agent-2026",
        "AI Agent をテーマにした 2 日間のハッカソン。エントリー受付中。",
        content=(
            "AI Agent Hackathon 2026\n"
            "開催日: 2026年11月14日(土) - 11月15日(日)\n"
            "会場: 東京・渋谷\n"
            "エントリー締切: 2026年10月31日\n"
            "参加費: 無料\n"
            "対象: AI Agent の開発に興味のあるエンジニア\n"
            "エントリーは公式フォームから受け付けています。"
        ),
        score=0.94,
    ),
    _r(
        "【終了】Tokyo AI Builders Meetup #12",
        "https://example-meetup.jp/tokyo-ai-12",
        "2026年8月に開催されたミートアップのレポート。",
        content=(
            "Tokyo AI Builders Meetup #12\n"
            "開催日: 2026年8月9日(日)\n"
            "申込締切: 2026年8月5日\n"
            "会場: 東京・大手町\n"
            "本イベントは終了しました。次回の告知をお待ちください。"
        ),
        score=0.71,
    ),
    _r(
        "DJ × テクノロジー コミュニティ「BeatLab」メンバー募集",
        "https://example-beatlab.jp/join",
        "音楽制作とプログラミングを横断するコミュニティ。随時参加受付。",
        content=(
            "BeatLab は DJ・トラックメイカーとエンジニアが集まるコミュニティです。\n"
            "活動開始: 2024年4月\n"
            "参加方法: Discord に参加するだけ。随時受け付けています。\n"
            "月に一度、制作物を持ち寄る会を開いています。"
        ),
        score=0.55,
    ),
    _r(
        "AI Agent とは何か - 仕組みと活用例をわかりやすく解説",
        "https://example-media.jp/what-is-ai-agent",
        "AI Agent の基本的な仕組みを解説した記事です。",
        content=(
            "AI Agent とは、目標を与えると自律的に手順を考えて実行するソフトウェアです。\n"
            "本記事では代表的なアーキテクチャと活用例を紹介します。"
        ),
        score=0.88,
    ),
    _r(
        "AI Agent Hackathon 2026 エントリー受付中 | Connpass",
        "https://example-connpass.jp/event/998877",
        "AI Agent をテーマにした 2 日間のハッカソン。",
        content=(
            "AI Agent Hackathon 2026\n"
            "2026年11月14日(土) 10:00 〜 11月15日(日) 18:00\n"
            "東京・渋谷\n"
            "エントリー締切: 2026年10月31日"
        ),
        score=0.90,
    ),
    _r(
        "地域おこし協力隊 × テクノロジー 募集説明会",
        "https://example-local.jp/tech-briefing",
        "地方自治体と技術者をつなぐ取り組みの説明会。",
        content=(
            "地域の課題を技術で解決する取り組みの説明会です。\n"
            "日程は決まり次第お知らせします。\n"
            "エンジニアの参加を歓迎しています。"
        ),
        score=0.34,
    ),
    _r(
        "Founders Program for AI Startups (Remote)",
        "https://example-founders.com/program",
        "AI 領域の起業家向けプログラム。リモート参加可。",
        content=None,  # **本文が取れない候補**
        score=0.66,
    ),
]

# --- Serper 相当（snippet のみ）--------------------------------------------
# **content は入れない。** 本文を返さない provider を「返すふり」で
# 比較すると、本文取得を別に選ぶ必要があるという結論が消える。
SERPER_RESULTS: list[SearchResult] = [
    _r(r.title, r.url, r.snippet, content=None, score=None) for r in TAVILY_RESULTS
]

# --- 本文取得の結果 ---------------------------------------------------------
# Serper 構成で本文取得を挟んだときに返る想定の本文。
# **1 件はわざと取れない。** 取得失敗を含めない比較は実際と合わない。
FETCHED_PAGES: dict[str, PageContent] = {
    r.url: PageContent(url=r.url, title=r.title, content=r.content)
    for r in TAVILY_RESULTS
    if r.content
}

# 本文取得に失敗する URL。
UNFETCHABLE_URLS = [r.url for r in TAVILY_RESULTS if not r.content]

# 同じ催しの重複（URL 違い）。
DUPLICATE_URLS = (
    "https://example-hack.jp/agent-2026",
    "https://example-connpass.jp/event/998877",
)

# 記事であって機会ではない URL。
ARTICLE_URLS = ("https://example-media.jp/what-is-ai-agent",)

# 本人が自分では探さないが、目標につながる候補。
SERENDIPITOUS_URLS = (
    "https://example-beatlab.jp/join",
    "https://example-local.jp/tech-briefing",
)

# 受付が終わっている候補。
CLOSED_URLS = ("https://example-meetup.jp/tokyo-ai-12",)
