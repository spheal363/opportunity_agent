"""① Goal Analysis の入出力。"""

from pydantic import BaseModel, Field


class GoalAnalysisInput(BaseModel):
    """**「いま」と「将来」を分けて渡す。**

    以前は全部 `goals` に入っていて、分析が長期目標へ寄り、今回の希望
    （音楽・曲作り・ポケモン）が落ちた。
    """

    # 初回フォームのメイン欄。**検索の中心はこれ。**
    wants_now: str | None = None
    # 任意。**今回の探索の必須条件にしない。**
    future_goals: str | None = None
    occupation: str | None = None
    skills: list[str] = Field(default_factory=list)
    interests: list[str] = Field(default_factory=list)
    goals: list[str] = Field(default_factory=list)
    about: str | None = None


class GoalAnalysisOutput(BaseModel):
    """**「今回探したい機会」と「長期的な背景目標」を分ける。**

    実測で、7 行の希望（音楽イベント・曲作り・ハッカソン・ポケモン・起業）が
    `goal_summary` 1〜2 文へ潰れ、起業とプロダクト開発だけが残った。
    後段（検索計画）には要約しか渡らないため、**そこで落ちた希望は二度と
    戻らない。** 原文に近い形を別の欄で保つ。
    """

    goal_summary: str
    # **今回探したい機会。本人の言葉に近い形で、1 項目 1 希望。**
    # ここを要約しない。検索計画はこれを見て方向を作る。
    wanted_now: list[str] = Field(default_factory=list)
    # 長期的な背景目標。**今回の探索の必須条件にしない。**
    background_goals: list[str] = Field(default_factory=list)
    goal_directions: list[str] = Field(default_factory=list)
    # 「AI × Music」のように複数の興味の交差点。Serendipity 探索の種になる。
    # **必須ではない。** 交差点が無い希望（単独の興味）もそのまま扱う。
    interest_connections: list[str] = Field(default_factory=list)
