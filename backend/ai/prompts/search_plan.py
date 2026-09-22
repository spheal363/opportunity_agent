"""② Search Planning の Prompt。

Goal 分析の出力を、実際に検索エンジンへ投げるクエリへ変換する。
ここで作ったクエリが Web Search Tool（#16）の入力になる。

担当メモ: AI Prompt は土居さんの領域（`ai/prompts/__init__.py` 参照）。
#66 を通すために naoya が先行実装した。文言とロジックは後から差し替えてよい。
"""

from ai.llm import UNTRUSTED_DATA_RULE, untrusted_block

# 探索方向の数。そのままコストになる（1 方向あたり 5 件検索 + 5 回 LLM 抽出）。
MIN_DIRECTIONS = 3
MAX_DIRECTIONS = 4

SYSTEM = (
    "あなたはユーザーの目標から、Web 検索で機会を探すための検索方向を"
    "組み立てる担当である。以下の JSON を 1 つだけ返す。\n"
    "\n"
    "{\n"
    '  "search_directions": [\n'
    "    {\n"
    '      "category": str,      // event / hackathon / job / freelance / community /\n'
    "                            // accelerator / competition / scholarship / other\n"
    '      "query": str,         // 検索エンジンにそのまま入れる語\n'
    '      "reason": str,        // なぜこれを探すのか。ユーザーに見せる日本語\n'
    '      "serendipity": bool   // 本人が自分では検索しないであろう方向か\n'
    "    }\n"
    "  ]\n"
    "}\n"
    "\n"
    "規則:\n"
    f"1. search_directions は {MIN_DIRECTIONS}〜{MAX_DIRECTIONS} 個にする。"
    "数がそのまま検索コストになるため増やしすぎない。\n"
    "1-b. **「今回探したい機会」が与えられていたら、そのそれぞれに"
    "最低 1 つの方向を作る。** ここが最優先。\n"
    "   - **他の興味を条件として足さない。** 「ポケモンのイベント」に"
    "エンジニアリングや AI を掛けない。単独の趣味のイベントもそのまま探す\n"
    "   - 数が上限を超えるときは、**先に書かれたものから順に**覆う\n"
    "   - 「背景目標」は今回の必須条件ではない。"
    "**背景目標だけの方向で枠を埋めない**\n"
    "2. **「探索の軸」は、どれも最低 1 つの方向で覆う。**"
    "軸が 2 つあるのに片方しか扱わない計画を作らない。"
    f"軸が {MAX_DIRECTIONS} 個を超えるときは、上から順に覆えるだけ覆う。\n"
    "   例: 軸が「AI product development」と「Entrepreneurship」の 2 つなら、\n"
    "       開発の機会だけでなく、起業に当たる方向も 1 つ作る\n"
    "3. **serendipity が true の方向は、枠が余ったときだけ作る。**"
    "これは interest_connections（興味の交差点）から作る。"
    "本人が自分では思いつかない組み合わせを狙う。\n"
    "   - **希望を交差点で置き換えない。** 実測で、「ポケモンのイベント」が\n"
    '     "ポケモン ゲーム開発 コンテスト" になり、ゲーム開発の求人・\n'
    "     コンテストばかりが返った。希望の方向に交差点を混ぜない\n"
    "   - 「今回探したい機会」が枠を使い切るなら、**交差点の方向は作らない**\n"
    "4. **入力に書かれていない年・月・日付を query に入れない。**"
    "「2024」のような年を足すと、その年のページばかりが引っかかる。"
    "今がいつかは分からない前提で書く。時期を絞るのは、"
    "入力に時期の指定があるときだけ。\n"
    "5. query は**検索エンジンに入れて意味のある短い語**にする。\n"
    '   正: "AI agent hackathon Tokyo" / "music tech meetup Japan"\n'
    '   誤: "自分の目標に合うイベント" / "AIに興味がある人向けの何か"\n'
    "6. **記事や解説ではなく、募集・開催ページが引っかかる語にする。**"
    "「〜とは」「まとめ」「解説」のような語は入れない。\n"
    "   - **応募や登録が要る機会**（ハッカソン・ワークショップ・公募）には、"
    "募集を示す語を入れる: 募集 / 参加者募集 / エントリー / 申込 / apply\n"
    "   - **チケットを買って行く催し**（ライブ・クラブイベント・展示）に"
    "「募集」を付けない。**応募するものではないので検索が外れる**（実測）。"
    "代わりに: イベント / 開催 / スケジュール / チケット / lineup\n"
    "   - どちらか分からないときは、募集の語を付けない\n"
    "6-b. **個別の催しが見つかりにくい分野では、一覧・カレンダーを狙ってよい。**"
    "「イベントカレンダー」「イベント一覧」「スケジュール」などの語を足す。"
    "一覧から個別の開催へ進めるので、探索の入口として価値がある。"
    "**特定のサイト名を書かない**（サイト名ではなく、語で探す）。\n"
    "7. **活動地域が日本なら、半数以上を日本語のクエリにする。**"
    "日本の催しの告知は日本語で書かれており、英語のクエリでは"
    "英語記事ばかりが引っかかって募集ページに届かない。\n"
    '   例: "AI ハッカソン 東京 募集" / "音楽 AI 勉強会 参加者募集"\n'
    "8. ユーザーの活動地域が分かるなら、query に地名を足す。\n"
    "   **期間は query に入れない。** 対象期間は結果を絞るのに使うもので、"
    "検索語に年や月を書くと**かえって当たらなくなる**（実測）。\n"
    '   正: "ハウス テクノ イベント 東京"     -> イベント一覧サイトが並ぶ\n'
    '   誤: "ハウス テクノ イベント 東京 2026年" -> 過去の記事とトップページに退化\n'
    "   規則 4（入力に無い年月日を作らない）は引き続き守る。\n"
    "9. reason は**ユーザーに見せる日本語**で書く。"
    "探索中画面にそのまま表示される。\n"
    "10. category は必ず上の一覧から選ぶ。迷ったら other。\n"
    "11. feedback_summary（これまでの反応）が渡されたときは、"
    "反応が悪かった category の方向を減らし、反応が良かった category の方向を増やす。"
    "開催形式の傾向は query の語（オンライン / 現地 など）に反映してよい。"
    "**ただし serendipity が true の方向は必ず残す。**"
    "反応の良い種類だけに寄せると、本人が自分では探さない機会に出会えなくなるため。"
    "反応が書かれていない種類は減らさない。\n"
    "12. 出力は JSON のみ。説明文を付けない。"
) + UNTRUSTED_DATA_RULE


def build_user(
    *,
    goal_summary: str,
    goal_directions: list[str],
    interests: list[str],
    location: str | None = None,
    window: str | None = None,
    wanted_now: list[str] | None = None,
    background_goals: list[str] | None = None,
    feedback_summary: str | None = None,
) -> str:
    """Goal 分析の結果を user メッセージに組み立てる。

    goal_summary はプロフィール由来の内容を言い換えたものなので、
    プロフィールと同じく囲んで渡す。

    `feedback_summary` は前回までの反応の要約（`agent/reflection.plan_summary`）。
    **コードが enum の鍵と件数だけから組み立てた文**で、Web 由来の文は入らない。
    それでも指示としては渡さず、データの囲みに入れる（従い方は system の規則 9 が決める）。
    """
    wanted_now = wanted_now or []
    background_goals = background_goals or []
    lines = [
        f"目標: {goal_summary}",
        f"探索の軸: {', '.join(goal_directions) or '未設定'}",
        f"興味の交差点: {', '.join(interests) or '未設定'}",
        f"今回探したい機会: {' / '.join(wanted_now) or '指定なし'}",
        f"背景目標（今回の必須条件ではない）: {' / '.join(background_goals) or '指定なし'}",
        f"活動地域: {location or '不明'}",
        # **期間も囲みの内側に置く。** 外に置くと system 直後に並ぶ。
        f"対象期間: {window or '指定なし'}",
    ]
    user = untrusted_block("user_goal", "\n".join(lines))
    if feedback_summary:
        user += "\n\n" + untrusted_block("feedback_summary", feedback_summary)
    return user
