"""② Search Planning。

Goal 分析の出力から検索方向を組み立てる。ここで作ったクエリが
Web Search Tool（#16）の入力になる。

**Serendipity 狙いの方向を最低 1 つ確保する。** LLM が出さなかった場合は
interest_connections から補う。この製品の独自性に直結するため、
出力任せにしない。
"""

from ai.llm import generate_structured
from ai.orcarouter import ModelTier
from ai.prompts import search_plan as prompt
from ai.routing import Step
from ai.schemas.search_plan import SearchDirection, SearchPlanOutput
from logging_config import get_logger
from schemas.opportunity import OpportunityType

logger = get_logger(__name__)

# 抽出（#18）・Goal 分析（#30）と同じ理由。既定の 2048 では JSON が切れる。
SEARCH_PLAN_MAX_TOKENS = 8192


def plan_search(
    *,
    goal_summary: str,
    goal_directions: list[str],
    interest_connections: list[str],
    location: str | None = None,
    window: str | None = None,
    wanted_now: list[str] | None = None,
    background_goals: list[str] | None = None,
    feedback_summary: str | None = None,
    # **工程ごとの振り分け（#26-b）に任せる。** None なら routing 表が決める。
    tier: ModelTier | None = None,
) -> list[SearchDirection]:
    """検索方向を組み立てる。

    `feedback_summary` があれば、前回までの反応を計画に反映させる（#50）。
    反応の良い種類に寄せても **Serendipity の方向は `_ensure_serendipity` が必ず残す。**
    """
    result = generate_structured(
        schema=SearchPlanOutput,
        system=prompt.SYSTEM,
        user=prompt.build_user(
            goal_summary=goal_summary,
            goal_directions=goal_directions,
            interests=interest_connections,
            location=location,
            window=window,
            wanted_now=wanted_now,
            background_goals=background_goals,
            feedback_summary=feedback_summary,
        ),
        step=Step.SEARCH_PLAN,
        tier=tier,
        max_tokens=SEARCH_PLAN_MAX_TOKENS,
    )

    directions = result.data.search_directions[: prompt.MAX_DIRECTIONS]
    directions = _ensure_serendipity(directions, interest_connections)

    logger.info(
        "search_plan.done directions=%d serendipity=%d",
        len(directions),
        sum(1 for d in directions if d.serendipity),
    )
    return directions


def _ensure_serendipity(
    directions: list[SearchDirection], interest_connections: list[str]
) -> list[SearchDirection]:
    """Serendipity 狙いの方向を最低 1 つ確保する。

    LLM が 1 つも出さなかったとき、興味の交差点から 1 つ足す。
    交差点が無ければ諦める（無い情報から作らない）。
    """
    if any(d.serendipity for d in directions) or not interest_connections:
        return directions

    seed = interest_connections[0]
    logger.info("search_plan.serendipity_added")
    return [
        *directions,
        SearchDirection(
            category=OpportunityType.EVENT,
            # 「AI × Music」-> 「AI Music event」
            query=f"{seed.replace('×', '').replace('  ', ' ').strip()} event",
            reason=f"{seed}の交差点は自分では検索しにくいため",
            serendipity=True,
        ),
    ]
