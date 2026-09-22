"""Jev へ渡す評価基準。**言葉で定義する。**

Jev の Score は「水準の並び」を渡し、その位置を返す仕組み
（https://docs.typesafe.ai/primitives/score）。モデルは番号ではなく
**説明文だけを見る**ため、水準の書き方がそのまま評価基準になる。

**関連性と意外性を別の質問にする。** 1 つの質問に 2 つの軸を混ぜると、
公式が「多次元の質問」として confidence が下がる原因に挙げている。
"""

from __future__ import annotations

# 関連性。0 が無関係、4 が直接つながる。
RELEVANCE_LEVELS: list[str] = [
    "本人の目標とまったく関係がない",
    "かすかに触れているが、目標に寄与しない",
    "分野は重なるが、目標に向けた一歩にはならない",
    "目標に向けた一歩になりうる",
    "目標に直接つながり、強く合致している",
]

# 意外性。**関連していることが前提。** 関連しない外れを高く出さない。
SERENDIPITY_LEVELS: list[str] = [
    "本人が自分で検索して必ず見つける、ありふれた選択肢",
    "本人が思いつきやすい範囲にある",
    "やや外れるが、言われれば納得できる",
    "本人の検索では出てこないが、目標につながる",
    "本人がまず探さない領域でありながら、目標に確かにつながる",
]

# **評価の対象は「機会」であって記事ではない。**
# 現行構成で TOP3 に解説記事が混ざった実例があり、そこを明示的に尋ねる。
IS_OPPORTUNITY = (
    "これは人が参加・応募・登録できる機会か、"
    "またはそこから個別の機会へたどれるイベント一覧・カレンダーか。"
    "イベント、ハッカソン、コミュニティ、求人、公募、プログラムが該当する。"
    "**イベント一覧・イベントカレンダー・開催情報のまとめページも該当する**"
    "（個別のイベントそのものではないが、そこから個別の開催へたどれる）。"
    "解説記事、過去の開催レポート、企業紹介、製品紹介は該当しない。"
)

# 抜粋だけで判断できるかどうか。**足りないことを減点にしない。**
SNIPPET_IS_SUFFICIENT = (
    "この抜粋だけで、機会の内容と受付状況を判断できるか。"
    "日程・締切・応募方法のいずれかが抜粋に書かれていなければ、判断できない。"
)

# すべての質問に添える注意。**抜粋の欠落を終了や無関係の根拠にしない。**
#
# 検索の抜粋は本文の一部でしかなく、締切が書かれていないことは珍しくない。
# 「期限が書いていない＝終わっている」と読むと、生きている募集を落とす。
NO_DEADLINE_IS_NOT_EVIDENCE = (
    "抜粋に日程や締切が書かれていないことを、"
    "終了している根拠にも、関係がない根拠にもしてはならない。"
    "書かれていないことは、単に分からないということである。"
)


def relevance_question(extra: str = "") -> dict:
    return {
        "type": "score",
        "instructions": (
            "本人の目標と、この機会の関連の強さを評価する。" + NO_DEADLINE_IS_NOT_EVIDENCE + extra
        ),
        "criteria": RELEVANCE_LEVELS,
    }


def serendipity_question(extra: str = "") -> dict:
    return {
        "type": "score",
        "instructions": (
            "本人が自分では探さなかったであろう度合いを評価する。"
            "ただし目標につながっていることが前提で、"
            "単に無関係なものを高く評価してはならない。" + extra
        ),
        "criteria": SERENDIPITY_LEVELS,
    }


def is_opportunity_question() -> dict:
    return {"type": "noul", "instructions": IS_OPPORTUNITY + NO_DEADLINE_IS_NOT_EVIDENCE}


def snippet_sufficient_question() -> dict:
    return {"type": "noul", "instructions": SNIPPET_IS_SUFFICIENT}


def to_0_100(score: float | None, levels: list[str]) -> int:
    """Jev の Score を既存の 0-100 に合わせる。

    Jev が返すのは 0〜(水準数-1) の期待値。既存の `select_top` は
    `score + 0.3 * serendipity_score` を 0-100 の前提で計算しているため、
    **同じ土俵に乗せてから渡す。**

    `score` が無い（質問が返らなかった）場合は 0 にしない。0 は「無関係」
    という判断であって、「分からない」ではない。呼び出し側が扱えるよう
    None のまま返さず、ここでは最低位ではなく中央値に寄せる…のではなく、
    **判断できなかったことを呼び出し元へ伝える**ために -1 を返す。
    """
    if score is None:
        return -1
    span = max(len(levels) - 1, 1)
    clamped = max(0.0, min(float(score), float(span)))
    return round(clamped / span * 100)
