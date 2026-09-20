"""① Goal Analysis の Prompt。

プロフィールから「この人が何を目指しているか」を構造化する。
探索の起点になるステップで、ここがずれると後段すべてがずれる。

担当メモ: AI Prompt は土居さんの領域（`ai/prompts/__init__.py` 参照）。
#20 を通すために naoya が先行実装した。文言とロジックは後から差し替えてよい。
"""

from ai.llm import UNTRUSTED_DATA_RULE, untrusted_block

SYSTEM = (
    "あなたはユーザーのプロフィールを読み、その人が何を目指しているかを"
    "言語化する担当である。以下の JSON を 1 つだけ返す。\n"
    "\n"
    "{\n"
    '  "goal_summary": str,            // 1〜2 文。この人が目指していること\n'
    '  "goal_directions": [str],       // 3〜5 個。探索の軸になる領域\n'
    '  "interest_connections": [str]   // 2〜4 個。複数の興味の交差点\n'
    "}\n"
    "\n"
    "規則:\n"
    "1. goal_summary は本人の言葉を言い換えるだけにする。"
    "書かれていない願望を足さない。\n"
    "2. goal_directions は**英語の短い名詞句**にする"
    "（例: AI product development, Entrepreneurship）。"
    "後で検索クエリの材料にするため、日本語の文章にしない。\n"
    "3. interest_connections は「AI × Music」のように、"
    "**別々の興味を掛け合わせた交差点**を書く。\n"
    "   - 単独の興味をそのまま並べない（「AI」だけ、は不可）\n"
    "   - 本人が明示していない組み合わせでよい。"
    "むしろ本人が気づいていない組み合わせに価値がある\n"
    "   - 掛け合わせる要素はプロフィールに書かれているものに限る\n"
    "4. 情報が乏しくても何か返す。空配列は返さない。\n"
    "5. 出力は JSON のみ。説明文を付けない。"
) + UNTRUSTED_DATA_RULE


def build_user(
    *,
    occupation: str | None,
    skills: list[str],
    interests: list[str],
    goals: list[str],
    about: str | None,
) -> str:
    """プロフィールを user メッセージに組み立てる。

    **プロフィールは本人が書いた自由文を含む。** `about` に指示文を書けば
    Prompt Injection になりうるため、外部データと同じく囲んで渡す。
    自分のプロフィールなので攻撃者とは限らないが、囲む側で区別しない。
    """
    lines = [
        f"職業: {occupation or '未記入'}",
        f"スキル: {', '.join(skills) or '未記入'}",
        f"興味: {', '.join(interests) or '未記入'}",
        f"目標: {', '.join(goals) or '未記入'}",
        f"自由記述: {about or '未記入'}",
    ]
    return untrusted_block("user_profile", "\n".join(lines))
