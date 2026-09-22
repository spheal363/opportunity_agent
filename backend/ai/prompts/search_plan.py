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
    "2. **「探索の軸」は、どれも最低 1 つの方向で覆う。**"
    "軸が 2 つあるのに片方しか扱わない計画を作らない。"
    f"軸が {MAX_DIRECTIONS} 個を超えるときは、上から順に覆えるだけ覆う。\n"
    "   例: 軸が「AI product development」と「Entrepreneurship」の 2 つなら、\n"
    "       開発の機会だけでなく、起業に当たる方向も 1 つ作る\n"
    "3. **serendipity が true の方向を最低 1 つ含める。**"
    "これは interest_connections（興味の交差点）から作る。"
    "本人が自分では思いつかない組み合わせを狙う。\n"
    "4. **入力に書かれていない年・月・日付を query に入れない。**"
    "「2024」のような年を足すと、その年のページばかりが引っかかる。"
    "今がいつかは分からない前提で書く。時期を絞るのは、"
    "入力に時期の指定があるときだけ。\n"
    "5. query は**検索エンジンに入れて意味のある短い語**にする。\n"
    '   正: "AI agent hackathon Tokyo" / "music tech meetup Japan"\n'
    '   誤: "自分の目標に合うイベント" / "AIに興味がある人向けの何か"\n'
    "6. **記事や解説ではなく、募集・開催ページが引っかかる語にする。**"
    "「〜とは」「まとめ」「解説」のような語は入れない。"
    "代わりに募集を示す語を入れる。\n"
    "   日本語なら: 募集 / 開催 / 参加者募集 / エントリー / 申込\n"
    "   英語なら:   call for participants / apply / registration / tickets\n"
    "7. **活動地域が日本なら、半数以上を日本語のクエリにする。**"
    "日本の催しの告知は日本語で書かれており、英語のクエリでは"
    "英語記事ばかりが引っかかって募集ページに届かない。\n"
    '   例: "AI ハッカソン 東京 募集" / "音楽 AI 勉強会 参加者募集"\n'
    "8. ユーザーの活動地域が分かるなら、query に地名を足す。"
    "「対象期間」が与えられているときは、その範囲に開催・募集があるものを狙う。"
    "**対象期間に含まれる年や月は入力に書かれているので、query に使ってよい。**"
    "規則 4 が禁じているのは、入力に無い年月日を作ることであって、"
    "与えられた期間を使うことではない。\n"
    '   正: "AI ハッカソン 東京 2026年10月 募集"（対象期間の中の月）\n'
    '   誤: "AI ハッカソン 東京 2024 募集"（入力に無い年）\n'
    "9. reason は**ユーザーに見せる日本語**で書く。"
    "探索中画面にそのまま表示される。\n"
    "10. category は必ず上の一覧から選ぶ。迷ったら other。\n"
    "11. 出力は JSON のみ。説明文を付けない。"
) + UNTRUSTED_DATA_RULE


def build_user(
    *,
    goal_summary: str,
    goal_directions: list[str],
    interests: list[str],
    location: str | None = None,
    window: str | None = None,
) -> str:
    """Goal 分析の結果を user メッセージに組み立てる。

    goal_summary はプロフィール由来の内容を言い換えたものなので、
    プロフィールと同じく囲んで渡す。
    """
    lines = [
        f"目標: {goal_summary}",
        f"探索の軸: {', '.join(goal_directions) or '未設定'}",
        f"興味の交差点: {', '.join(interests) or '未設定'}",
        f"活動地域: {location or '不明'}",
        # **期間も囲みの内側に置く。** 外に置くと system 直後に並ぶ。
        f"対象期間: {window or '指定なし'}",
    ]
    return untrusted_block("user_goal", "\n".join(lines))
