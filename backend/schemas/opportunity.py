"""Opportunity スキーマ。

情報を 3 種類に分けて扱う。
  1. Web から取得した事実 (title / start_at / deadline / location ...)
  2. AI が生成した評価 (score / reason / serendipity_score / match_reasons)
  3. ユーザーとの関係 (status)
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, field_validator


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


class Correction(BaseModel):
    """詳細確認で直した 1 項目。**上書きせず履歴として積む（#47）。**"""

    field: str
    before: str | None = None
    after: str | None = None
    source: str
    checked_at: Timestamp = None


class OpportunitySummary(BaseModel):
    """一覧で返す形。

    **`verified` は「詳細確認を実行したか」であって、
    日付・場所・受付・参加資格がすべて確認済みという意味ではない（#47）。**
    何が確認できたかは `confirmed_fields` を見る。
    """

    opportunity_id: str
    type: OpportunityType
    title: str
    description: str | None = None
    url: str | None = None
    start_at: Timestamp = None
    # **複数日開催を期間として出すために一覧でも返す（#47）。**
    # これが無いと、一覧で「10/17〜10/18」を出せず、日ごとに同じ企画が並ぶ。
    end_at: Timestamp = None
    end_at_is_date_only: bool | None = None
    location: str | None = None
    deadline: Timestamp = None

    score: int = Field(ge=0, le=100)
    serendipity_score: int = Field(ge=0, le=100)
    reason: str | None = None
    match_reasons: list[str] = Field(default_factory=list)

    verified: bool = False
    # --- 検索専用モデル経路（#47）---
    # **どの希望から出た候補か。** 元の入力もそのまま返す。
    wish: str | None = None
    wish_source: str | None = None
    # **一覧の候補は未確認。** 引用があることは公式で確認した意味ではない。
    # 詳細確認で確認できた項目だけがここに入る。
    confirmed_fields: list[str] = Field(default_factory=list)
    corrections: list[Correction] = Field(default_factory=list)

    # **列を足す前からある行は NULL。** `ALTER TABLE` で足した列は既存行が
    # NULL になり、モデル側の default は新規挿入にしか効かない。
    # 空として読む。**「値が無い」と「[] である」を区別する必要はない。**
    @field_validator("confirmed_fields", "corrections", "match_reasons", "unknowns", mode="before")
    @classmethod
    def _none_is_empty(cls, v):
        return [] if v is None else v

    detail_checked_at: Timestamp = None
    # **評価したか。** False の候補は score を表示に使わない（架空の点数を出さない）。
    evaluated: bool = False
    # 会期の途中 1 日で参加できるか／全日必須か。**根拠が無ければ null。**
    participation_span: str | None = None
    # 評価で挙がった、判断に必要な未確認事項。**推測で埋めない。**
    unknowns: list[str] = Field(default_factory=list)
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
    # **探索期間との関係（#47）。** DB の列ではなく、run の期間から毎回求める。
    # None は「期間が分からない run」（この列が付く前の run）。
    # **受付状況とは別の軸。** 期間内でも申込が締め切られていることがある。
    window_status: str | None = None
    window_note: str | None = None
    # **希望した地域との照合（#47）。** 受付・期間とはさらに別の軸。
    # `unknown` を一致として扱わない。
    region_match: str | None = None
    region_note: str | None = None
    # 抽出できた開催地の都道府県。**会場名だけでは地域を判定できない。**
    region: str | None = None
    online_participation: bool | None = None
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
    format: OpportunityFormat | None = None
    eligibility: str | None = None
    cost: int | None = None
    # **一部の区分だけ無料、ということがある。** cost が null でも
    # 「記載が無い」のか「区分によって違う」のかで伝え方が変わる。
    cost_kind: str | None = None

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
