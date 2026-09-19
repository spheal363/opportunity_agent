"""③ Opportunity Extraction の入出力。

ここでは評価をせず、Web 上の事実の構造化だけを行う。
取得できなかった項目は推測で埋めず null にする。
"""

from datetime import datetime

from pydantic import BaseModel

from schemas.opportunity import OpportunityFormat, OpportunityType


class ExtractionInput(BaseModel):
    source_url: str
    page_content: str


class ExtractedOpportunity(BaseModel):
    title: str
    type: OpportunityType
    description: str | None = None
    url: str | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    deadline: datetime | None = None
    location: str | None = None
    format: OpportunityFormat | None = None
    eligibility: str | None = None
    cost: int | None = None
