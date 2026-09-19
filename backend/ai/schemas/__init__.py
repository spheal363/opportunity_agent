"""AI 各処理の Input / Output スキーマ。

LLM の出力は自由文ではなくここで定義した JSON Schema に従わせ、
Backend 側で Validation する。不正な出力は Retry の対象とする。
"""

from ai.schemas.evaluation import EvaluationInput, EvaluationOutput
from ai.schemas.extraction import ExtractedOpportunity, ExtractionInput
from ai.schemas.goal_analysis import GoalAnalysisInput, GoalAnalysisOutput
from ai.schemas.recommendation import RecommendationInput, RecommendationOutput
from ai.schemas.reflection import ReflectionInput, ReflectionOutput
from ai.schemas.search_plan import SearchDirection, SearchPlanInput, SearchPlanOutput
from ai.schemas.selection import SelectionCandidate, SelectionInput, SelectionOutput
from ai.schemas.verification import VerificationInput, VerificationOutput

__all__ = [
    "EvaluationInput",
    "EvaluationOutput",
    "ExtractedOpportunity",
    "ExtractionInput",
    "GoalAnalysisInput",
    "GoalAnalysisOutput",
    "RecommendationInput",
    "RecommendationOutput",
    "ReflectionInput",
    "ReflectionOutput",
    "SearchDirection",
    "SearchPlanInput",
    "SearchPlanOutput",
    "SelectionCandidate",
    "SelectionInput",
    "SelectionOutput",
    "VerificationInput",
    "VerificationOutput",
]
