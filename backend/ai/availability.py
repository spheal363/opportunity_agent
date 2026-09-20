"""受付状況の判定。

**`verified` とは別の軸。**

  verified      その情報を公式ページで確認できたか
  availability  いま応募・参加できるか

確認できたうえで受付終了、ということがある。両方を持つ。

**推測しない。** 締切が未来というだけでは `open` にしない（満員かもしれない）。
`deadline` が null は「受付終了でも受付中でもない」ので `unknown`。
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from schemas.opportunity import OpportunityType


class Availability(StrEnum):
    """いま応募・参加できるか。

    **`open` は「受付中を確認できた」という意味。** 参加資格を満たすことや
    空き枠があることまでは保証しない。画面の文言もその範囲に合わせる。
    """

    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


# 開催が終われば参加できない種類。開始しただけでは終わらない。
_ENDS = frozenset(
    {
        OpportunityType.EVENT,
        OpportunityType.HACKATHON,
        OpportunityType.COMPETITION,
    }
)


def as_utc(value: datetime | None) -> datetime | None:
    """SQLite から読んだ naive な日時を UTC とみなす。

    **SQLite は tz を保持しない。** ORM 経由で読むと `tzinfo=None` で返るため、
    そのまま `now(UTC)` と比べると TypeError になる。保存時は UTC へ揃えて
    いる（`ai/schemas/extraction.to_utc`）ので、読み出し時に付け直す。
    """
    if value is None:
        return None
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


def from_dates(
    *,
    opportunity_type: str | None,
    deadline: datetime | None,
    end_at: datetime | None,
    now: datetime | None = None,
) -> tuple[Availability, str | None]:
    """日時だけで判定する。評価より前に使う。

    **`closed` と言い切れるものだけ `closed` にする。** 残りは `unknown`。
    `start_at` は見ない。開始済みでも参加できる機会がある（community / job）し、
    イベントでも当日参加できることがある。終わったかどうかは `end_at` で見る。
    """
    now = now or datetime.now(UTC)

    deadline = as_utc(deadline)
    if deadline is not None and deadline < now:
        return Availability.CLOSED, "申込の締切が過ぎています"

    end_at = as_utc(end_at)
    if end_at is not None and end_at < now and _ends(opportunity_type):
        return Availability.CLOSED, "開催が終了しています"

    # 締切が未来でも「受付中」とは限らない（満員・中止がある）。
    return Availability.UNKNOWN, None


def _ends(opportunity_type: str | None) -> bool:
    try:
        return OpportunityType(opportunity_type) in _ENDS
    except ValueError:
        return False


def is_actionable(availability: str | None) -> bool:
    """行動できる推薦に混ぜてよいか。

    **`unknown` は混ぜる。** 確認できていないだけで、終わったとは限らない。
    画面では「要確認」と示す。
    """
    return availability != Availability.CLOSED
