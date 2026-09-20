"""③ Opportunity Extraction の入出力。

ここでは評価をせず、Web 上の事実の構造化だけを行う。
取得できなかった項目は推測で埋めず null にする。
"""

from datetime import UTC, datetime
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field

from schemas.opportunity import OpportunityFormat, OpportunityType

# ページ本文の上限。Tavily の extract は 40,000 文字を超えることがあり、
# そのまま渡すとトークンを食う。催しの情報はページ前半に集まるため頭から取る。
MAX_PAGE_CONTENT_CHARS = 12_000


def _require_timezone(value: datetime | None) -> datetime | None:
    """タイムゾーンを持たない日時を拒否する。

    「9/21 19:00」とだけ書かれた日本のページから naive な値が返ったとき、
    それを UTC として保存すると 9 時間ずれる。LLM には必ずオフセットを
    付けさせ、付いていなければ Schema Validation で弾いて問い直す
    （`generate_structured` が理由を添えて再試行する）。

    判断できない日時は LLM 側で null にさせる。ずれた値より無い方がよい。
    """
    if value is not None and value.tzinfo is None:
        raise ValueError(
            "日時にタイムゾーンオフセットが必要です"
            "（日本の催しなら +09:00）。判断できない場合は null にしてください"
        )
    return value


def _to_utc(value: datetime | None) -> datetime | None:
    """DB は UTC で持つ（SQLite は tz を保持しないため）。"""
    return value.astimezone(UTC) if value is not None else None


# タイムゾーン必須。保存前に UTC へ揃える。
# BeforeValidator だとパース前の文字列を受け取り naive を素通しするため After を使う。
AwareDatetime = Annotated[datetime | None, AfterValidator(_require_timezone)]


class ExtractionInput(BaseModel):
    source_url: str
    page_content: str


class ExtractedOpportunity(BaseModel):
    title: str
    type: OpportunityType
    description: str | None = None
    url: str | None = None
    start_at: AwareDatetime = None
    end_at: AwareDatetime = None
    deadline: AwareDatetime = None
    location: str | None = None
    format: OpportunityFormat | None = None
    eligibility: str | None = None
    # 無料は 0、不明は null。混同しない。
    cost: int | None = Field(default=None, ge=0)

    def to_utc(self) -> "ExtractedOpportunity":
        """日時を UTC に揃えた写しを返す。DB へ入れる直前に呼ぶ。"""
        return self.model_copy(
            update={
                "start_at": _to_utc(self.start_at),
                "end_at": _to_utc(self.end_at),
                "deadline": _to_utc(self.deadline),
            }
        )
