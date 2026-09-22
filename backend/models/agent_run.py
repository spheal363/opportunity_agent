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

    # --- この run の最終選定 ---
    # **順位順の opportunity_id。** Opportunity 側の run_id は同じ URL を再発見すると
    # 上書きされるため、過去 run の選定結果は保てない。ここに記録する。
    #
    # 保証するのは「どれをどの順で選んだか」だけ。**候補の内容は最新値**で、
    # 選定時点の本文を保存するものではない。
    selected_ids: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 3 件に満たなかった理由。後から同じ内容を返せるよう run に持つ。
    shortfall_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    # この run が対象にした期間（#47）。{'start','end','tz'}。
    # **run 開始時に確定した値をそのまま残す。** 後から今日の日付で作り直さない。
    search_window: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # ① Goal Analysis の全出力（#47）。**要約だけでは追跡できない。**
    goal_analysis: Mapped[dict | None] = mapped_column(JSON, nullable=True)

    # 検索で見つかった候補（#47）。[{title, url, direction}]。
    # **本文を読んだかどうかに関わらず全件。** 読んだ分だけが Opportunity 行になる。
    # 保存するのはタイトルと URL だけで、**本文は残さない**。
    search_candidates: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # 検索専用モデルの回答そのものと引用 URL（#47）。
    # **一覧は本文を取りに行かないので、根拠はこれしか残らない。**
    # 切れた回答・解析できなかった回答も、そのまま残す。
    discovery_answers: Mapped[list | None] = mapped_column(JSON, nullable=True)
    # **この run の入力原文。** プロフィールを後から編集しても、
    # 過去 run の探索条件が置き換わらないようにする（#47）。
    # 古い run は None。**現在のプロフィールで補わない。**
    wishes_source: Mapped[str | None] = mapped_column(Text, nullable=True)
    region_source: Mapped[str | None] = mapped_column(String, nullable=True)
    # `selected_ids` の先頭いくつが「おすすめ」か。**評価できなければ 0。**
    recommended_count: Mapped[int] = mapped_column(Integer, default=0)

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
