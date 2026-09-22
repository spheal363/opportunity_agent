"""① Goal Analysis。

プロフィールから goal_summary / goal_directions / interest_connections を作る。
探索計画（#66）の入力になる。

プロフィールは本人が書いた自由文を含むため、CHEAP は使わない。
`about` に指示文を仕込めば Prompt Injection になりうる
（`ai/llm.py` の実測: cheap は 1/2 で突破される）。
"""

from ai.llm import generate_structured
from ai.orcarouter import ModelTier
from ai.prompts import goal_analysis as prompt
from ai.routing import Step
from ai.schemas.goal_analysis import GoalAnalysisInput, GoalAnalysisOutput
from logging_config import get_logger

logger = get_logger(__name__)

# 抽出（#18）と同じ理由。既定の 2048 では reasoning が上限を食い JSON が切れる。
GOAL_ANALYSIS_MAX_TOKENS = 8192


def analyze_goal(
    profile: GoalAnalysisInput,
    *,
    tier: ModelTier | None = None,
) -> GoalAnalysisOutput:
    """プロフィールから目標を構造化する。"""
    result = generate_structured(
        schema=GoalAnalysisOutput,
        system=prompt.SYSTEM,
        user=prompt.build_user(
            occupation=profile.occupation,
            skills=profile.skills,
            interests=profile.interests,
            goals=profile.goals,
            about=profile.about,
        ),
        step=Step.GOAL_ANALYSIS,
        tier=tier,
        max_tokens=GOAL_ANALYSIS_MAX_TOKENS,
    )
    out = result.data
    # プロフィール由来の内容は Log へ出さない。件数だけ残す。
    logger.info(
        "goal_analysis.done directions=%d connections=%d",
        len(out.goal_directions),
        len(out.interest_connections),
    )
    return out
