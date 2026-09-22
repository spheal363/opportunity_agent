"""④ Opportunity Evaluation + ⑤ TOP3 Selection + ⑥ Recommendation。

`agent/loop.py` の `_evaluate_and_select` が使う。

**コストの形を意識している。**

    全 N 件を評価   -> N 回の LLM 呼び出し
    TOP3 を選ぶ     -> 0 回（スコアで決める）
    推薦理由を書く  -> 3 回

選定は LLM に投げない。`score` と `serendipity_score` が既にあるので、
そこから決められる。全件に推薦理由を書かせるのも無駄なので TOP3 に絞る。
"""

from collections.abc import Mapping

from ai import cost
from ai.concurrency import map_parallel
from ai.jev.client import JevError
from ai.jev.evaluation import evaluate_with_jev
from ai.llm import LLMError, generate_structured
from ai.orcarouter import ModelTier
from ai.prompts import evaluation as eval_prompt
from ai.prompts import recommendation as rec_prompt
from ai.schemas.evaluation import EvaluationOutput
from ai.schemas.recommendation import RecommendationOutput
from config import get_settings
from logging_config import get_logger

logger = get_logger(__name__)

EVALUATION_MAX_TOKENS = 8192
TOP_N = 3

# TOP3 を選ぶときの serendipity の重み。
# 0 にすると王道の求人ばかりが並び、この製品である意味がなくなる。
# 1 にすると目標から遠いものが上位に来る。
_SERENDIPITY_WEIGHT = 0.3
# 学習（agent/reflection.py）が意外性の重みを動かしてよい範囲。
# **狭く取る。** 反応が偏っても、王道ばかり・遠いものばかりにはしない。
SERENDIPITY_WEIGHT_RANGE = (0.2, 0.45)
# 学習が 1 件の候補の並べ替えに足し引きしてよい点数の上限（score と同じ 0-100 の尺度）。
# 2 件の差は最大でも 20 点しか動かない。
# 評価の差が大きい候補同士の順位は、学習だけでは入れ替わらない。
MAX_LEARNED_ADJUSTMENT = 10.0


def evaluate(
    *,
    goal_summary: str,
    interest_connections: list[str],
    opportunity: dict,
    tier: ModelTier = ModelTier.STANDARD,
) -> EvaluationOutput:
    """1 件を評価する。

    `EVALUATOR=jev` のときは Jev を使い、**確信が持てないときと失敗したときは
    既存 LLM へ戻す。** 戻した分の費用は LLM 側の欄に乗る（#65 の A/B 比較で
    「Jev に替えた分だけ安くなる」とは限らないため、別々に数える）。
    """
    if get_settings().evaluator.strip().lower() == "jev":
        out = _try_jev(
            goal_summary=goal_summary,
            interest_connections=interest_connections,
            opportunity=opportunity,
        )
        if out is not None:
            return out

    return _evaluate_with_llm(
        goal_summary=goal_summary,
        interest_connections=interest_connections,
        opportunity=opportunity,
        tier=tier,
    )


def _try_jev(
    *, goal_summary: str, interest_connections: list[str], opportunity: dict
) -> EvaluationOutput | None:
    """Jev で評価する。**駄目なら None を返し、呼び出し元が LLM へ戻す。**"""
    try:
        return evaluate_with_jev(
            goal_summary=goal_summary,
            interest_connections=interest_connections,
            opportunity=opportunity,
        )
    except JevError as exc:
        # 1 件の失敗で評価全体を止めない。LLM へ戻して続ける。
        #
        # **低確信とは別に数える。** これは「確信が持てなかった」のではなく
        # 「呼べなかった」。同じ欄に積むと、A/B 比較で見たいフォールバック率に
        # 接続エラーが紛れ込む。
        cost.record_jev_hard_failure()
        logger.warning("evaluation.jev_failed reason=%s", exc)
        return None


def _evaluate_with_llm(
    *,
    goal_summary: str,
    interest_connections: list[str],
    opportunity: dict,
    tier: ModelTier,
) -> EvaluationOutput:
    result = generate_structured(
        schema=EvaluationOutput,
        system=eval_prompt.SYSTEM,
        user=eval_prompt.build_user(
            goal_summary=goal_summary,
            interests=interest_connections,
            opportunity=opportunity,
        ),
        tier=tier,
        max_tokens=EVALUATION_MAX_TOKENS,
    )
    return result.data


def evaluate_many(
    *,
    goal_summary: str,
    interest_connections: list[str],
    opportunities: list[dict],
    tier: ModelTier = ModelTier.STANDARD,
) -> tuple[list[tuple[str, EvaluationOutput]], list[str]]:
    """複数件を評価する。戻り値は ([(opportunity_id, 評価)], 失敗した id)。

    **1 件の失敗で全体を捨てない。** 抽出（#18）と同じ方針。
    """

    def one(opportunity: dict) -> tuple[str, EvaluationOutput | None]:
        opportunity_id = opportunity["opportunity_id"]
        try:
            return opportunity_id, evaluate(
                goal_summary=goal_summary,
                interest_connections=interest_connections,
                opportunity=opportunity,
                tier=tier,
            )
        except LLMError as exc:
            logger.warning("evaluation.failed id=%s reason=%s", opportunity_id, exc)
            return opportunity_id, None

    # 1 件ずつ独立した呼び出し。直列にすると待ち時間がそのまま積み上がる。
    results = map_parallel(opportunities, one)

    done = [(i, out) for i, out in results if out is not None]
    failed = [i for i, out in results if out is None]

    logger.info("evaluation.done ok=%d failed=%d", len(done), len(failed))
    return done, failed


def select_top(
    evaluated: list[tuple[str, EvaluationOutput]],
    *,
    limit: int = TOP_N,
    adjustments: Mapping[str, float] | None = None,
    serendipity_weight: float | None = None,
) -> list[str]:
    """TOP3 を選ぶ。

    **LLM に投げない。** score と serendipity_score が既にあるので、
    そこから決められる。1 回分の呼び出しと待ち時間を節約する。

    score だけで並べると王道の求人ばかりになる。serendipity を重みづけで
    混ぜ、意外性のあるものが上位に来る余地を残す。

    `adjustments` と `serendipity_weight` は前回までの反応から学んだ補正
    （`agent/reflection.py`）。

      - **並べ替えにだけ使い、score は書き換えない。** AI の評価と学習結果を混ぜない
        （.claude/rules/architecture.md の「3 つのデータ分離」）
      - 評価の出力（score / serendipity_score）の後に足すので、評価器が Jev でも LLM でも同じに効く
      - **ここでも上限で切る。** 呼び出し側の値が壊れていても、学習が評価を覆さない
    """
    adjustments = adjustments or {}
    low, high = SERENDIPITY_WEIGHT_RANGE
    weight = (
        _SERENDIPITY_WEIGHT
        if serendipity_weight is None
        else min(max(serendipity_weight, low), high)
    )

    def key(pair: tuple[str, EvaluationOutput]) -> float:
        opportunity_id, out = pair
        bonus = adjustments.get(opportunity_id, 0.0)
        bonus = max(-MAX_LEARNED_ADJUSTMENT, min(MAX_LEARNED_ADJUSTMENT, bonus))
        return out.score + weight * out.serendipity_score + bonus

    ranked = sorted(evaluated, key=key, reverse=True)
    return [opportunity_id for opportunity_id, _ in ranked[:limit]]


def recommend(
    *,
    goals: list[str],
    opportunity: dict,
    evaluation: EvaluationOutput,
    tier: ModelTier = ModelTier.STANDARD,
) -> RecommendationOutput:
    """「なぜあなたにこれを薦めるのか」を書く。TOP3 にだけ呼ぶ。"""
    result = generate_structured(
        schema=RecommendationOutput,
        system=rec_prompt.SYSTEM,
        user=rec_prompt.build_user(
            goals=goals,
            opportunity=opportunity,
            evaluation=evaluation.model_dump(),
        ),
        tier=tier,
        max_tokens=EVALUATION_MAX_TOKENS,
    )
    return result.data
