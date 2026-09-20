"""④ Opportunity Evaluation + ⑤ TOP3 Selection + ⑥ Recommendation。

`agent/loop.py` の `_evaluate_and_select` が使う。

**コストの形を意識している。**

    全 N 件を評価   -> N 回の LLM 呼び出し
    TOP3 を選ぶ     -> 0 回（スコアで決める）
    推薦理由を書く  -> 3 回

選定は LLM に投げない。`score` と `serendipity_score` が既にあるので、
そこから決められる。全件に推薦理由を書かせるのも無駄なので TOP3 に絞る。
"""

from ai.llm import LLMError, generate_structured
from ai.orcarouter import ModelTier
from ai.prompts import evaluation as eval_prompt
from ai.prompts import recommendation as rec_prompt
from ai.schemas.evaluation import EvaluationOutput
from ai.schemas.recommendation import RecommendationOutput
from logging_config import get_logger

logger = get_logger(__name__)

EVALUATION_MAX_TOKENS = 8192
TOP_N = 3

# TOP3 を選ぶときの serendipity の重み。
# 0 にすると王道の求人ばかりが並び、この製品である意味がなくなる。
# 1 にすると目標から遠いものが上位に来る。
_SERENDIPITY_WEIGHT = 0.3


def evaluate(
    *,
    goal_summary: str,
    interest_connections: list[str],
    opportunity: dict,
    tier: ModelTier = ModelTier.STANDARD,
) -> EvaluationOutput:
    """1 件を評価する。"""
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
    done: list[tuple[str, EvaluationOutput]] = []
    failed: list[str] = []

    for opportunity in opportunities:
        opportunity_id = opportunity["opportunity_id"]
        try:
            out = evaluate(
                goal_summary=goal_summary,
                interest_connections=interest_connections,
                opportunity=opportunity,
                tier=tier,
            )
        except LLMError as exc:
            logger.warning("evaluation.failed id=%s reason=%s", opportunity_id, exc)
            failed.append(opportunity_id)
            continue
        done.append((opportunity_id, out))

    logger.info("evaluation.done ok=%d failed=%d", len(done), len(failed))
    return done, failed


def select_top(evaluated: list[tuple[str, EvaluationOutput]], *, limit: int = TOP_N) -> list[str]:
    """TOP3 を選ぶ。

    **LLM に投げない。** score と serendipity_score が既にあるので、
    そこから決められる。1 回分の呼び出しと待ち時間を節約する。

    score だけで並べると王道の求人ばかりになる。serendipity を重みづけで
    混ぜ、意外性のあるものが上位に来る余地を残す。
    """
    ranked = sorted(
        evaluated,
        key=lambda pair: (pair[1].score + _SERENDIPITY_WEIGHT * pair[1].serendipity_score),
        reverse=True,
    )
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
