"""Opportunity スキーマ。

情報を 3 種類に分けて扱う。
  1. Web から取得した事実 (title / start_at / deadline / location ...)
  2. AI が生成した評価 (score / reason / serendipity_score / match_reasons)
  3. ユーザーとの関係 (status)
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field


def _assume_utc(value: datetime | None) -> datetime | None:
    """SQLite は tz を保持しないため、naive な値は UTC とみなす。

    これをしないと JSON に tz 指定が付かず、Frontend の `new Date(...)` が
    ローカル時刻として解釈してしまう。
    """
    if value is not None and value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value


# 常に tz 付きで返す datetime
Timestamp = Annotated[datetime | None, AfterValidator(_assume_utc)]


class OpportunityType(StrEnum):
    EVENT = "event"
    HACKATHON = "hackathon"
    JOB = "job"
    FREELANCE = "freelance"
    COMMUNITY = "community"
    ACCELERATOR = "accelerator"
    COMPETITION = "competition"
    SCHOLARSHIP = "scholarship"
    OTHER = "other"


class OpportunityFormat(StrEnum):
    OFFLINE = "offline"
    ONLINE = "online"
    HYBRID = "hybrid"


class Availability(StrEnum):
    """いま応募・参加できるか。`verified`（情報を確認できたか）とは別。"""

    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class OpportunityStatus(StrEnum):
    DISCOVERED = "discovered"
    RECOMMENDED = "recommended"
    INTERESTED = "interested"
    REGISTERED = "registered"
    ATTENDED = "attended"
    DISMISSED = "dismissed"


class OpportunitySummary(BaseModel):
    """GET /api/opportunities（TOP3 一覧）で返す形。"""

    opportunity_id: str
    type: OpportunityType
    title: str
    description: str | None = None
    url: str | None = None
    start_at: Timestamp = None
    location: str | None = None
    deadline: Timestamp = None

    score: int = Field(ge=0, le=100)
    serendipity_score: int = Field(ge=0, le=100)
    reason: str | None = None
    match_reasons: list[str] = Field(default_factory=list)

    verified: bool = False
    # **verified とは別の軸。** open は「受付中を確認できた」という意味で、
    # 参加資格や空き枠までは保証しない。
    availability: Availability = Availability.UNKNOWN
    availability_reason: str | None = None
    # **いつ時点の確認か。** 古い結果を今の状態として読まないために必ず対で見る。
    availability_checked_at: Timestamp = None
    # **出典に時刻が書かれていたか。** false のとき時刻を表示すると、
    # こちらが 00:00 へ正規化した値を出典の値として見せることになる。
    # **`None` は「分からない」。** false（出典に時刻があった）とは違う。
    # 不明のときは時刻を表示しない（確かめていない時刻を見せない）。
    start_at_is_date_only: bool | None = None
    deadline_is_date_only: bool | None = None
    # **この URL は申込先か、情報源か。** True なら申込先は未確認。
    url_is_source_only: bool = True
    # 検証で本文から読み取れた申込先。**同一サイトは根拠にしない。**
    application_url: str | None = None
    # 本人が取れる行動。特定できなければ null で、推薦には出さない。
    recommended_action: str | None = None
    status: OpportunityStatus = OpportunityStatus.DISCOVERED


class OpportunityDetail(OpportunitySummary):
    """GET /api/opportunities/{id}（詳細画面）で返す形。"""

    source: str | None = None
    end_at: Timestamp = None
    format: OpportunityFormat | None = None
    eligibility: str | None = None
    cost: int | None = None
    # **一部の区分だけ無料、ということがある。** cost が null でも
    # 「記載が無い」のか「区分によって違う」のかで伝え方が変わる。
    cost_kind: str | None = None

    end_at_is_date_only: bool | None = None
    # **その締切が何に対するものか。** 早割の期限を申込締切として見せない。
    deadline_kind: str | None = None
    # 判断の根拠になったページ上の表記。
    deadline_quote: str | None = None

    verified_at: Timestamp = None
    verification_source: str | None = None
    availability_source: str | None = None


class InterestResult(BaseModel):
    """POST /api/opportunities/{id}/interest のレスポンス。"""

    opportunity_id: str
    status: OpportunityStatus
    verified: bool
    registration_url: str | None = None
    warnings: list[str] = Field(default_factory=list)
