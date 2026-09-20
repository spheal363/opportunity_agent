"""⑥ Recommendation Generation の Prompt。

「なぜあなたにこれを薦めるのか」を書く。TOP3 にだけ生成する。

**`highlights` は今どこからも読まれていないが、意図的に残している。**
カード UI に短い訴求点を並べる想定で #05 が定義したもの。載せるには
DB 列・API・Frontend の型が要り、事前共有が必要（docs/development.md）。
まず動くものを作ってから UI を詰める方針なので、生成だけ先に通しておく。
TOP3 にしか呼ばないためコストの影響も小さい（1 探索あたり 3 回）。

なお `evaluation_summary`（④ Evaluation）は 20 件すべてに生成されていた
ため、同じ「未使用」でもトークンの効き方が違う。そちらは外した。

担当メモ: AI Prompt は土居さんの領域。#21 を通すために naoya が先行実装した。
"""

from ai.llm import UNTRUSTED_DATA_RULE, untrusted_block

SYSTEM = (
    "あなたはユーザーに機会を薦める担当である。以下の JSON を 1 つだけ返す。\n"
    "\n"
    "{\n"
    '  "reason": str,        // 2-3 文。なぜこの人に薦めるのか\n'
    '  "highlights": [str]   // 2-3 個。短い訴求点\n'
    "}\n"
    "\n"
    "規則:\n"
    "1. reason は**この人の目標と結びつけて**書く。"
    "一般的な紹介文にしない。\n"
    "   悪い例: 「AIに関する注目のイベントです」\n"
    "   良い例: 「AIプロダクト開発の経験を増やしたいという目標に対し、"
    "2日間で実際に動くものを作れます」\n"
    "2. **ユーザーに直接語りかける日本語**で書く。そのまま画面に出る。\n"
    "3. 与えられた事実だけを使う。日時や条件を creative に補わない。\n"
    "4. 懸念（concerns）があれば reason の中で正直に触れる。"
    "良いことだけ並べない。\n"
    "5. 出力は JSON のみ。説明文を付けない。"
) + UNTRUSTED_DATA_RULE


def build_user(*, goals: list[str], opportunity: dict, evaluation: dict) -> str:
    goal_lines = [f"- {g}" for g in goals] or ["- 未設定"]
    lines = [
        "# この人の目標",
        *goal_lines,
        "",
        "# 機会",
        f"title: {opportunity.get('title')}",
        f"type: {opportunity.get('type')}",
        f"description: {opportunity.get('description') or '不明'}",
        f"location: {opportunity.get('location') or '不明'}",
        f"start_at: {opportunity.get('start_at') or '不明'}",
        f"deadline: {opportunity.get('deadline') or '不明'}",
        f"cost: {opportunity.get('cost') if opportunity.get('cost') is not None else '不明'}",
        "",
        "# 評価",
        f"score: {evaluation.get('score')}",
        f"serendipity_score: {evaluation.get('serendipity_score')}",
        f"match_reasons: {', '.join(evaluation.get('match_reasons') or []) or 'なし'}",
        f"concerns: {', '.join(evaluation.get('concerns') or []) or 'なし'}",
    ]
    return untrusted_block("recommendation_target", "\n".join(lines))
