"""④ Opportunity Evaluation の Prompt。

この人にとってどれだけ価値があるかを評価する。
**score と serendipity_score は別の軸。** 混ぜない。

担当メモ: AI Prompt は土居さんの領域。#21 を通すために naoya が先行実装した。
"""

from ai.llm import UNTRUSTED_DATA_RULE, untrusted_block

SYSTEM = (
    "あなたはユーザーにとって、ある機会がどれだけ価値があるかを評価する担当である。"
    "以下の JSON を 1 つだけ返す。\n"
    "\n"
    "{\n"
    '  "score": int,                 // 0-100。目標への近さ\n'
    '  "serendipity_score": int,     // 0-100。自分では見つけられなさ\n'
    '  "match_reasons": [str],       // 1-4 個。合致した要素（短い語）\n'
    '  "concerns": [str]             // 0-3 個。懸念。無ければ空\n'
    "}\n"
    "\n"
    "**score と serendipity_score は別の軸である。混同しない。**\n"
    "\n"
    "score は「この人の目標にどれだけ近いか」。\n"
    "  90-100 目標そのもの。スキルも条件も合う\n"
    "  70-89  目標に直結する。多少の条件差はある\n"
    "  40-69  関連はあるが遠い\n"
    "  0-39   ほぼ関係ない\n"
    "\n"
    "serendipity_score は「本人が自分では検索しなかっただろう度合い」。\n"
    "  90-100 複数の興味の交差点。本人も気づいていない組み合わせ\n"
    "  70-89  本人の関心の隣接領域。言われれば納得する\n"
    "  40-69  やや意外性がある\n"
    "  0-39   本人が普通に検索して見つける\n"
    "\n"
    "**王道の求人は score が高く serendipity_score は低い。**\n"
    "**興味の交差点にある小さなイベントは score が中程度でも "
    "serendipity_score が高くなりうる。** どちらも価値がある。\n"
    "\n"
    "規則:\n"
    "1. match_reasons は短い語にする（例: AI Agent, Tokyo, 未経験可）。文章にしない。\n"
    "2. concerns には事実に基づく懸念だけ書く"
    "（例: 締切が過ぎている、英語必須、有料）。推測で不安を作らない。\n"
    "3. 情報が欠けている項目を理由に score を下げない。"
    "不明は不明として扱う。\n"
    "4. 出力は JSON のみ。説明文を付けない。"
) + UNTRUSTED_DATA_RULE


def build_user(*, goal_summary: str, interests: list[str], opportunity: dict) -> str:
    """評価対象と、評価の基準になるユーザー情報を組み立てる。

    機会の情報は Web 由来の Untrusted Data。ユーザー情報も自由文を含む。
    どちらも囲む。
    """
    lines = [
        "# この人について",
        f"目標: {goal_summary}",
        f"興味の交差点: {', '.join(interests) or '未設定'}",
        "",
        "# 評価する機会",
    ]
    for key in (
        "title",
        "type",
        "description",
        "location",
        "format",
        "start_at",
        "deadline",
        "eligibility",
        "cost",
        "source",
    ):
        value = opportunity.get(key)
        lines.append(f"{key}: {value if value is not None else '不明'}")
    return untrusted_block("evaluation_target", "\n".join(lines))
