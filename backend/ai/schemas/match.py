"""おすすめの選定に使う評価の I/O（#47）。

**マッチ度は「AI による希望との適合度の目安」。**
正確さでも、受付中である確率でも、参加資格を満たす確率でもない。
その 3 つは別の軸（`verified` / `availability` / `eligibility`）で持つ。
"""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

# 1 回で評価する候補の数。**候補ごとに個別呼び出しをしない。**
MAX_CANDIDATES = 30


class MatchJudgement(BaseModel):
    """候補 1 件の評価。"""

    opportunity_id: str

    @model_validator(mode="before")
    @classmethod
    def _accept_id(cls, v):
        """`id` で返してくることがある（実測）。**取り違えないよう写すだけ。**"""
        if isinstance(v, dict) and "opportunity_id" not in v and "id" in v:
            return {**v, "opportunity_id": v["id"]}
        return v

    # **希望との適合度の目安。** 0-100。
    match: int = Field(ge=0, le=100)
    # どの希望に合うか。**原文の希望をそのまま写す。** 複数可。
    matched_wishes: list[str] = Field(default_factory=list)
    # 1〜2 文。**どの希望にどう合うのかを具体的に。**
    # 入力に無い好みや、候補に無い事実を足さない。
    reason: str = Field(max_length=200)
    # 判断に必要だが、取得済みの情報では分からないこと。
    # **推測で埋めず、ここに書く。**
    unknowns: list[str] = Field(default_factory=list)


class MatchOutput(BaseModel):
    """渡した候補すべての評価。**順位はここでは決めない。**"""

    judgements: list[MatchJudgement] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _accept_bare_list(cls, v):
        """配列だけを返してくることがある（実測）。包んで受け取る。"""
        if isinstance(v, list):
            return {"judgements": v}
        return v
