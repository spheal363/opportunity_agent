"""⑦ Verification の入出力。

日時・締切などの重要情報を LLM の記憶だけで判断せず、公式ページで再確認する。
"""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class VerificationInput(BaseModel):
    opportunity: dict
    latest_page_content: str


class VerificationOutput(BaseModel):
    # 情報を公式ページで確認できたか
    verified: bool
    verified_at: datetime | None = None
    verification_source: str | None = None
    changes_detected: bool = False
    warnings: list[str] = Field(default_factory=list)

    # **いま応募・参加できるか。`verified` とは別の軸。**
    # open は「受付中を確認できた」という意味で、参加資格や空き枠は保証しない。
    availability: Literal["open", "closed", "unknown"] = "unknown"
    availability_reason: str | None = None
