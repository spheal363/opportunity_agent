"""AgentRun / AgentLog。

Agent State を DB に持たせることで、途中で落ちても状態を追跡・再開できるようにする。
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class AgentRun(Base):
    __tablename__ = "agent_runs"

    run_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)

    status: Mapped[str] = mapped_column(String, default="queued")
    current_step: Mapped[str | None] = mapped_column(String, nullable=True)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    progress: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- 何がきっかけで始まったか（#84）---
    # manual はボタン・目標の保存。それ以外は Agent が自分で始めた探索
    # （services/auto_explore.py）。値は schemas.agent.AgentRunTrigger。
    #
    # **理由は決まった文面と数値だけ。** 候補のタイトルなど Web 由来の文は入れない。
    # 探索中画面とホームの通知にそのまま出るため。
    #
    # 既存 DB には db/migrate.py が `DEFAULT 'manual'` 付きで足す。列を足す前の
    # run はすべて手動だったので、既定値がそのまま正しい。
    trigger: Mapped[str] = mapped_column(String, default="manual")
    trigger_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # --- この run の最終選定 ---
    # **順位順の opportunity_id。** Opportunity 側の run_id は同じ URL を再発見すると
    # 上書きされるため、過去 run の選定結果は保てない。ここに記録する。
    #
    # 保証するのは「どれをどの順で選んだか」だけ。**候補の内容は最新値**で、
    # 選定時点の本文を保存するものではない。
    selected_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 3 件に満たなかった理由。後から同じ内容を返せるよう run に持つ。
    shortfall_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # コスト計測（OrcaRouter のモデル振り分けを見せるため）
    cost_jpy: Mapped[float] = mapped_column(Float, default=0.0)
    expensive_model_calls: Mapped[int] = mapped_column(Integer, default=0)
    # 工程別の使用量。ai/cost.py の CostTracker.to_dict() が作る形。
    usage_json: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )


class AgentLog(Base):
    __tablename__ = "agent_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    run_id: Mapped[str] = mapped_column(String, index=True)
    step: Mapped[str] = mapped_column(String)
    message: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
