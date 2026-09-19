"""⑦ Verification の入出力。

日時・締切などの重要情報を LLM の記憶だけで判断せず、公式ページで再確認する。
"""

from datetime import datetime

from pydantic import BaseModel, Field


class VerificationInput(BaseModel):
    opportunity: dict
    latest_page_content: str


class VerificationOutput(BaseModel):
    verified: bool
    verified_at: datetime | None = None
    verification_source: str | None = None
    changes_detected: bool = False
    warnings: list[str] = Field(default_factory=list)
