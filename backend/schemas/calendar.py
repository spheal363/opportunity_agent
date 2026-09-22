"""Calendar 連携スキーマ。"""

from pydantic import BaseModel, Field

from schemas.opportunity import Timestamp


class CalendarConflict(BaseModel):
    title: str
    start_at: Timestamp
    end_at: Timestamp


class CalendarEventPreview(BaseModel):
    """**実際に送る内容そのもの。**

    画面の確認表示は、候補の行からではなくこれを使う。別々に組み立てると、
    確認した内容と送信した内容がずれる（終日かどうか・終了時刻の仮置きなど）。
    """

    title: str
    start_at: Timestamp
    end_at: Timestamp
    # **出典に時刻が無かったので終日予定にする。** こちらが時刻を決めない。
    all_day: bool = False
    # 日時を解釈するタイムゾーン。画面にそのまま出す。
    timezone: str
    # 終了時刻が取れておらず、こちらが仮に置いた
    end_is_placeholder: bool = False
    location: str | None = None
    # 出典。予定の説明にも入る。
    source_url: str | None = None


class CalendarAvailability(BaseModel):
    available: bool
    conflicts: list[CalendarConflict] = Field(default_factory=list)
    # **登録する内容。** 日時が取れていない候補では None（登録できない）。
    event: CalendarEventPreview | None = None


class CalendarEventCreated(BaseModel):
    calendar_event_id: str
    status: str = "created"
