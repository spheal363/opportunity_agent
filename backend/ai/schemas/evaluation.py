"""④ Opportunity Evaluation の入出力。"""

from pydantic import BaseModel, Field


class EvaluationInput(BaseModel):
    user_profile: dict
    opportunity: dict


class EvaluationOutput(BaseModel):
    score: int = Field(ge=0, le=100)
    serendipity_score: int = Field(ge=0, le=100)

    # **None は「この評価器は語句を作らない」という意味。**
    #
    # Jev は分類・採点だけを返し、文字列を生成しない（公式が明記）。
    # そこを空文字や当たり障りのない語で埋めると、LLM が挙げた根拠と
    # 見分けがつかなくなる。**互換性を装わずに、無いことを無いと持つ。**
    #
    # 空リストは「語句を作る評価器だが、挙がらなかった」という別の状態。
    match_reasons: list[str] | None = Field(default_factory=list)
    concerns: list[str] | None = Field(default_factory=list)
    evaluation_summary: str | None = None

    # どの評価器が出したか。A/B 比較で結果の出どころを追うために持つ。
    evaluator: str = "llm"
    # 実際に答えたモデルのバージョン（Jev のときだけ入る）。
    evaluator_model: str | None = None
    # Jev の confidence。**正解率ではない**（公式が明記）。
    confidence: float | None = None
