"""Opportunity。Web 上の事実 / AI の評価 / ユーザーとの関係 を列レベルで分けて持つ。"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from db.base import Base


class Opportunity(Base):
    __tablename__ = "opportunities"

    opportunity_id: Mapped[str] = mapped_column(String, primary_key=True)
    user_id: Mapped[str] = mapped_column(String, index=True)
    run_id: Mapped[str | None] = mapped_column(String, index=True, nullable=True)

    # --- ① Web から取得した事実 ---
    type: Mapped[str] = mapped_column(String)
    title: Mapped[str] = mapped_column(String)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    url: Mapped[str | None] = mapped_column(String, nullable=True)
    source: Mapped[str | None] = mapped_column(String, nullable=True)
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deadline: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    format: Mapped[str | None] = mapped_column(String, nullable=True)
    eligibility: Mapped[str | None] = mapped_column(Text, nullable=True)
    cost: Mapped[int | None] = mapped_column(Integer, nullable=True)

    # --- ② AI が生成した評価 ---
    score: Mapped[int] = mapped_column(Integer, default=0)
    serendipity_score: Mapped[int] = mapped_column(Integer, default=0)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    match_reasons: Mapped[list] = mapped_column(JSON, default=list)

    # 何に対する締切・料金かの区別（#65 で見つかった取り違えへの対処）。
    #
    # **ページ全体の受付状況を一括で決めないための情報。** 早割の期限を
    # 申込締切として扱うと、終了した募集が受付中に見える。
    #
    # 旧い行は None。**当時の前提（deadline = 申込締切）のまま扱う。**
    deadline_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    deadline_quote: Mapped[str | None] = mapped_column(String, nullable=True)
    cost_kind: Mapped[str | None] = mapped_column(String, nullable=True)
    # **推薦する行動と、その対象。** 特定できなければ null。
    # null の候補は最終推薦に出さない（投稿作品・過去レポート・解説記事・
    # 検索一覧そのものを「応募できる機会」として出さないため）。
    recommended_action: Mapped[str | None] = mapped_column(String, nullable=True)
    # **申込先を確認できたか。** True は「この URL は取得元のページで、
    # 申込先として確かめたものではない」。情報源へのリンクとして扱う。
    url_is_source_only: Mapped[bool] = mapped_column(Boolean, default=True)
    # 検証で**本文から読み取れた**申込先。読み取れなければ null。
    # **同一サイトかどうかは根拠にしない。** 外部の申込サービスもある。
    application_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # 出典に時刻が書かれていたか。False でも「00:00 と書いてあった」ではなく
    # 「時刻の記載があった」という意味。日付だけなら True。
    # **`None` は「分からない」。** false（出典に時刻があった）とは違う。
    # 不明のときは時刻を表示せず、締切も当日中には切らない。
    start_at_is_date_only: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    end_at_is_date_only: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    deadline_is_date_only: Mapped[bool | None] = mapped_column(Boolean, nullable=True)

    # --- 受付状況（verified とは別軸）---
    #
    # **verified は「情報を確認できたか」、availability は「今応募・参加できるか」。**
    # 確認できたうえで受付終了、ということがある。
    #
    # open   受付中を**確認できた**。参加資格や空き枠まで保証するものではない
    # closed 受付終了・開催終了を**確認できた**
    # unknown どちらとも確認できていない。締切が未来というだけでは open にしない
    #
    # **最新の確認結果のみを持つ。** 再確認に失敗したときに古い open を
    # 今回の結果として返さないよう、checked_at と必ず対で読む。
    availability: Mapped[str] = mapped_column(String, default="unknown")
    availability_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    availability_checked_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # 何を見て判定したか（URL）。verification_source と同じとは限らない
    availability_source: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- 検証情報 ---
    verified: Mapped[bool] = mapped_column(Boolean, default=False)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    verification_source: Mapped[str | None] = mapped_column(String, nullable=True)

    # --- ③ ユーザーとの関係 ---
    status: Mapped[str] = mapped_column(String, default="discovered")

    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
