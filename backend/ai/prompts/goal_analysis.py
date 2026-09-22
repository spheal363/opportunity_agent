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
    '  "wanted_now": [str],            // 今回探したい機会。**1 項目 1 希望**\n'
    '  "background_goals": [str],      // 長期的な背景目標\n'
    '  "goal_directions": [str],       // 3〜5 個。探索の軸になる領域\n'
    '  "interest_connections": [str]   // 0〜4 個。複数の興味の交差点\n'
    "}\n"
    "\n"
    "規則:\n"
    "1. goal_summary は本人の言葉を言い換えるだけにする。"
    "書かれていない願望を足さない。\n"
    "1-b. **wanted_now には、本人が「参加したい」「見たい」「挑戦したい」と"
    "書いた機会を、1 つずつ分けて入れる。** 要約でまとめない。\n"
    "   - 本人の言葉に近い短い日本語にする（例:「ハウス/テクノの音楽イベント」）\n"
    "   - **書かれた希望を 1 つも落とさない。** 趣味・遊び・娯楽も対象。\n"
    "     仕事や成長につながらない希望でも、そのまま入れる\n"
    "   - **他の興味との関連を条件として足さない。**"
    "「ポケモンのイベント」を「ポケモン × エンジニアリング」にしない\n"
    "1-c. **background_goals には「将来〜したい」という長期の目標**を入れる。"
    "これは今回探す機会の必須条件ではない。"
    "wanted_now と background_goals に同じものを重ねて入れない。\n"
    "2. goal_directions は**英語の短い名詞句**にする"
    "（例: AI product development, Entrepreneurship）。"
    "後で検索クエリの材料にするため、日本語の文章にしない。\n"
    "3. interest_connections は「AI × Music」のように、"
    "**別々の興味を掛け合わせた交差点**を書く。\n"
    "   - 単独の興味をそのまま並べない（「AI」だけ、は不可）\n"
    "   - 本人が明示していない組み合わせでよい。"
    "むしろ本人が気づいていない組み合わせに価値がある\n"
    "   - 掛け合わせる要素はプロフィールに書かれているものに限る\n"
    "   - **交差点は必須ではない。** 無理に作らず、自然なものが無ければ"
    "空配列でよい。**wanted_now の希望を交差点へ置き換えない**\n"
    "4. 情報が乏しくても何か返す。"
    "ただし interest_connections だけは空配列でよい（規則 3）。\n"
    "5. 出力は JSON のみ。説明文を付けない。"
) + UNTRUSTED_DATA_RULE


def build_user(
    *,
    location: str | None = None,
    occupation: str | None,
    skills: list[str],
    interests: list[str],
    goals: list[str],
    about: str | None,
    wants_now: str | None = None,
    future_goals: str | None = None,
) -> str:
    """プロフィールを user メッセージに組み立てる。

    **プロフィールは本人が書いた自由文を含む。** `about` に指示文を書けば
    Prompt Injection になりうるため、外部データと同じく囲んで渡す。
    自分のプロフィールなので攻撃者とは限らないが、囲む側で区別しない。
    """
    # **本人がいま書いた希望が最優先。** 以前に選んだ興味タグや古い目標が
    # これと食い違うとき、タグ側を採らせない。
    lines = [f"いま、やってみたいこと（最優先。今回の探索の中心）: {wants_now or '未記入'}"]
    if future_goals:
        lines.append(f"将来の目標（補足。今回の必須条件ではない）: {future_goals}")
    lines.append(f"活動したい地域: {location or '未記入'}")

    if wants_now:
        # 新しい欄が埋まっているので、以前の項目は**参考**としてのみ添える。
        # 矛盾したら上の「いま、やってみたいこと」を採る。
        extra = [t for t in (occupation, ", ".join(skills), ", ".join(interests)) if t]
        if extra:
            lines.append(
                "（参考・以前の入力。上と食い違う場合は上を優先する）: " + " / ".join(extra)
            )
    else:
        # 新しい欄が空。**以前の入力しか手がかりが無い。**
        lines += [
            f"職業: {occupation or '未記入'}",
            f"スキル: {', '.join(skills) or '未記入'}",
            f"興味: {', '.join(interests) or '未記入'}",
            f"目標: {', '.join(goals) or '未記入'}",
            f"自由記述: {about or '未記入'}",
        ]
    return untrusted_block("user_profile", "\n".join(lines))
