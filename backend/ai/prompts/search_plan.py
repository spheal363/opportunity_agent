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
    "2. **serendipity が true の方向を最低 1 つ含める。**"
    "これは interest_connections（興味の交差点）から作る。"
    "本人が自分では思いつかない組み合わせを狙う。\n"
    "3. query は**検索エンジンに入れて意味のある短い語**にする。\n"
    '   正: "AI agent hackathon Tokyo" / "music tech meetup Japan"\n'
    '   誤: "自分の目標に合うイベント" / "AIに興味がある人向けの何か"\n'
    "4. query には地域や時期を必要に応じて入れる。"
    "ユーザーの活動地域が分かるなら地名を足す。\n"
    "5. reason は**ユーザーに見せる日本語**で書く。"
    "探索中画面にそのまま表示される。\n"
    "6. category は必ず上の一覧から選ぶ。迷ったら other。\n"
    "7. 出力は JSON のみ。説明文を付けない。"
) + UNTRUSTED_DATA_RULE


def build_user(
    *,
    goal_summary: str,
    goal_directions: list[str],
    interests: list[str],
    location: str | None = None,
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
    ]
    return untrusted_block("user_goal", "\n".join(lines))
