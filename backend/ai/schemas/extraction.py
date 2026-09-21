"""③ Opportunity Extraction の入出力。

ここでは評価をせず、Web 上の事実の構造化だけを行う。
取得できなかった項目は推測で埋めず null にする。
"""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated

from pydantic import AfterValidator, BaseModel, Field, model_validator

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


class DeadlineKind(StrEnum):
    """その締切が**何に対するもの**か。

    同じページに複数の締切が並ぶ。**どれを拾ったかで意味が反対になる。**

    実例（https://www.xsum.jp/gai）:

        応募締め切り  2026年8月21日（取り消し線・「応募を締め切りました」）
        早割り        9/30 迄
        イベント      10月7日

    ここで早割の 9/30 を締切として拾うと、**終了した募集が
    「9/30 まで受付中」に見える。**
    """

    # 推薦する行動（参加・応募）に対応する締切。**これだけが受付終了の根拠になる。**
    APPLICATION = "application"  # 応募締切
    REGISTRATION = "registration"  # 参加申込・参加登録の期限

    # 過ぎても参加はできる締切。**受付終了の根拠にしない。**
    EARLY_BIRD = "early_bird"  # 早割・先行販売
    SPEAKER = "speaker"  # 登壇者・発表者・出展者の募集
    OTHER = "other"

    # 何に対する締切か特定できなかった。**推測しない。**
    UNKNOWN = "unknown"


# 推薦する行動を閉ざす締切。これ以外は過ぎていても参加できることがある。
GATING_DEADLINES = frozenset({DeadlineKind.APPLICATION, DeadlineKind.REGISTRATION})


class CostKind(StrEnum):
    """参加費の区分。

    **一部の区分が無料でも、機会全体が無料とは限らない。**

    実例（https://www.xsum.jp/gai）: 定価 ¥20,000 / 早割 ¥8,000 と並んで
    「無料（受付にて証明書の提示）」の区分がある。これを見て cost=0 にすると、
    **有料のイベントが無料として推薦される。**
    """

    FREE = "free"  # 全体が無料と明記されている
    PAID = "paid"  # 有料の記載がある
    PARTIALLY_FREE = "partially_free"  # 一部の区分だけ無料
    UNKNOWN = "unknown"  # 記載が無い。**無料ではない。**


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

    # --- 何に対する条件か -------------------------------------------------
    #
    # **ページ全体の open/closed を一括で決めない。** 同じページで
    # 「登壇者募集は終了、一般参加は受付中」が起きる。

    deadline_kind: DeadlineKind = DeadlineKind.UNKNOWN
    # その締切の根拠になったページ上の表記。**後から人が確かめられるように残す。**
    deadline_quote: str | None = Field(default=None, max_length=200)
    cost_kind: CostKind = CostKind.UNKNOWN

    # --- 出典に時刻が書かれていたか ---------------------------------------
    #
    # **書かれていない時刻を作らない。** 日付だけのときは True にし、
    # 時刻部分はこちら側の正規化（00:00）であって出典の値ではないと示す。

    start_at_is_date_only: bool = False
    end_at_is_date_only: bool = False
    deadline_is_date_only: bool = False

    @model_validator(mode="after")
    def _guard(self) -> "ExtractedOpportunity":
        """**モデルの申告を鵜呑みにしない。** 決定的に整合させる。

        prompt で指示しても守られないことがある（実測で、時刻の無いページに
        09:00 / 17:00 を入れた）。ここは出力を受け取ったあとの砦。
        """
        # 日付だけと申告したなら、時刻はこちらで 00:00 に落とす。
        # モデルが入れた時刻をそのまま残すと、出典にある時刻と区別できない。
        for field in ("start_at", "end_at", "deadline"):
            if getattr(self, f"{field}_is_date_only") and getattr(self, field) is not None:
                value = getattr(self, field)
                object.__setattr__(
                    self, field, value.replace(hour=0, minute=0, second=0, microsecond=0)
                )

        # **一部が無料なだけ、あるいは記載が無いものを 0 円にしない。**
        if self.cost == 0 and self.cost_kind is not CostKind.FREE:
            object.__setattr__(self, "cost", None)
        # 有料と分かっているのに金額が 0 なのは矛盾。金額不明として扱う。
        if self.cost_kind is CostKind.PAID and self.cost == 0:
            object.__setattr__(self, "cost", None)
        return self

    def to_utc(self) -> "ExtractedOpportunity":
        """日時を UTC に揃えた写しを返す。DB へ入れる直前に呼ぶ。"""
        return self.model_copy(
            update={
                "start_at": _to_utc(self.start_at),
                "end_at": _to_utc(self.end_at),
                "deadline": _to_utc(self.deadline),
            }
        )
