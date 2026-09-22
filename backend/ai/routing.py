"""工程ごとのモデル振り分け方針（#26-b）。

**方針はここ 1 か所だけに書く。** 各 AI 関数が自前で tier を決めると、
「どの工程がどのモデルを使うか」を 1 か所で説明できなくなる。

    ai/<工程>.py  --(step)-->  ai/llm.py  --(routing)-->  tier  -->  OrcaRouter

## 何を根拠に「簡単」「難しい」を決めるか

工程名では決めない。次の 4 つで決める。

    入力の出所      Web 本文を読むか。外部由来のデータを読むか
    判断の重さ      事実の抽出・突き合わせか、語句の組み立てか
    呼び出し数      1 run あたり何回呼ぶか（費用と時間に直接効く）
    許容できる時間  直列の待ち時間に乗るか、並列に逃がせるか

## 外部由来のデータに CHEAP を使わない

cheap は Prompt Injection に 1/2 で突破される実測がある（`ai/llm.py`）。
**「Web 本文そのもの」だけでなく、それを LLM が要約・抽出した結果も外部由来**
として扱う。抽出結果の `description` に指示文が残っていれば、評価も推薦理由も
同じものを読む。由来を理由なく trusted に格上げしない。

この制約はコードで縛る（`_check_table`）。表を書き換えて CHEAP にしようとしても、
`reads_untrusted=True` の工程は import 時に落ちる。

## POWERFUL を通常 tier に置かない

powerful は 1 呼び出し 4.5 秒（#14 実測）。通常経路に置くと探索が止まって見える。
**Fallback でだけ上がる**（`ai/llm.py` の `_FALLBACK_TIERS`）。
デモのために呼び出しを足さない。

## 元へ戻す

`LLM_ROUTING=standard` で全工程が STANDARD に戻る（この表を無視する）。
振り分け前の挙動と同じになる。
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ai.orcarouter import ModelTier
from config import get_settings


class Step(StrEnum):
    """LLM を呼ぶ工程。**LLM を呼ばない工程はここに入れない。**

    入れないもの:
      search / fetch   Tool。LLM ではない
      prefilter        Jev。OrcaRouter の tier は持たない
      selection        コードで決まる（`ai/evaluation.py` の `select_top`）
      reflection       未接続
    """

    GOAL_ANALYSIS = "goal_analysis"
    DISCOVERY = "discovery"
    SEARCH_PLAN = "search_plan"
    EXTRACTION = "extraction"
    LINK_PICK = "link_pick"
    EVALUATION = "evaluation"
    RECOMMENDATION = "recommendation"
    VERIFICATION = "verification"


@dataclass(frozen=True)
class Route:
    """1 工程の振り分け。**理由を必ず持たせる。**

    理由は Log に出る。「なぜこの工程が安いモデルでよいのか」を
    実行ログだけで説明できるようにするため（#54）。
    """

    tier: ModelTier
    # 入力に外部由来のデータが含まれるか。True の工程は CHEAP にできない。
    reads_untrusted: bool
    # Log と表に出す一行。
    reason: str


# 工程ごとの方針。**変更はここだけ。**
#
# 現時点では全工程 STANDARD。#26-b では検索計画から 1 工程ずつ実測して
# 判定する方針で、実測で合格したものだけをここで下げる。
_ROUTES: dict[Step, Route] = {
    Step.GOAL_ANALYSIS: Route(
        tier=ModelTier.STANDARD,
        reads_untrusted=False,
        reason="本人のプロフィール自由文。外部本文は読まないが、about に指示文を書ける",
    ),
    Step.SEARCH_PLAN: Route(
        tier=ModelTier.STANDARD,
        reads_untrusted=False,
        reason="目標分析の出力から検索語を組み立てる。外部本文は読まない",
    ),
    Step.DISCOVERY: Route(
        tier=ModelTier.STANDARD,
        # **モデルの内側で Web を読む。** 本文はこちらの guard を通らないので、
        # 出力は事実として確定させず「検索で見つかった候補」として扱う。
        reads_untrusted=True,
        reason="検索専用モデルが内蔵検索で外部ページを読む。出力は未確認の候補",
    ),
    Step.EXTRACTION: Route(
        tier=ModelTier.STANDARD,
        reads_untrusted=True,
        reason="Web 本文をそのまま読む。8回/run で費用の過半を占める",
    ),
    Step.LINK_PICK: Route(
        tier=ModelTier.STANDARD,
        reads_untrusted=True,
        reason="一覧ページから取った題名を読む。Web 由来",
    ),
    Step.EVALUATION: Route(
        tier=ModelTier.STANDARD,
        reads_untrusted=True,
        reason="抽出結果を読む。要約済みでも外部由来",
    ),
    Step.RECOMMENDATION: Route(
        tier=ModelTier.STANDARD,
        reads_untrusted=True,
        reason="抽出・評価の結果を読み、画面にそのまま出る文を書く",
    ),
    Step.VERIFICATION: Route(
        tier=ModelTier.STANDARD,
        reads_untrusted=True,
        reason="公式ページの本文をそのまま読む",
    ),
}


class RoutingError(RuntimeError):
    """振り分け表が制約に反している。**import 時に落とす。**"""


def _check_table(routes: dict[Step, Route]) -> None:
    """表そのものを検査する。

    **後から表だけ書き換えて制約を破れないようにする。** レビューで気づく前に
    落とす。全工程が揃っていることも見る（足りないと既定へ黙って落ちる）。
    """
    missing = [s for s in Step if s not in routes]
    if missing:
        raise RoutingError(f"振り分けの無い工程があります: {[s.value for s in missing]}")

    unsafe = [s.value for s, r in routes.items() if r.reads_untrusted and r.tier is ModelTier.CHEAP]
    if unsafe:
        raise RoutingError(
            f"外部由来のデータを読む工程に CHEAP は使えません: {unsafe}"
            "（cheap は Prompt Injection に 1/2 で突破される実測がある）"
        )

    powerful = [s.value for s, r in routes.items() if r.tier is ModelTier.POWERFUL]
    if powerful:
        raise RoutingError(
            f"POWERFUL を通常の tier に置かないでください: {powerful}"
            "（1 呼び出し 4.5 秒。上がるのは Fallback のときだけ）"
        )


_check_table(_ROUTES)


def route_for(step: Step) -> Route:
    """この工程の振り分けを返す。

    `LLM_ROUTING=standard` のときは**表を無視して STANDARD**。
    振り分けを入れる前の挙動へ 1 つの環境変数で戻せるようにするため。
    理由の文言は「戻してある」と分かるものに差し替える。
    """
    route = _ROUTES[step]
    if get_settings().llm_routing.strip().lower() == "standard":
        return Route(
            tier=ModelTier.STANDARD,
            reads_untrusted=route.reads_untrusted,
            reason="LLM_ROUTING=standard のため振り分けを使わない",
        )
    return route


def table() -> list[tuple[Step, Route]]:
    """表を並び順のまま返す。ドキュメント生成とテストが使う。"""
    return [(step, _ROUTES[step]) for step in Step]
