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

from ai.schemas.extraction import GATING_DEADLINES, DeadlineKind
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
    deadline_kind: str | None = None,
    deadline_is_date_only: bool = False,
) -> tuple[Availability, str | None]:
    """日時だけで判定する。評価より前に使う。

    **`closed` と言い切れるものだけ `closed` にする。** 残りは `unknown`。
    `start_at` は見ない。開始済みでも参加できる機会がある（community / job）し、
    イベントでも当日参加できることがある。終わったかどうかは `end_at` で見る。

    ## 締切は「何に対するものか」で扱いを変える

    **ページ全体の受付状況を一括で決めない。** 同じページに
    「登壇者募集は終了、一般参加は受付中」が並ぶ。

    受付終了の根拠にしてよいのは、**推薦する行動（参加・応募）に対応する
    締切だけ**。早割の期限や登壇者募集の締切が過ぎていても、参加はできる。

    `deadline_kind` が None のものは、区分を持たなかった頃に抽出した行。
    当時の prompt は `deadline` を「申込締切」として書かせていたので、
    **その前提のまま扱う。** 後から意味を変えない。
    """
    now = now or datetime.now(UTC)

    deadline = as_utc(deadline)
    if deadline is not None and _is_past(deadline, now, date_only=deadline_is_date_only):
        gating, reason = _deadline_gates_action(deadline_kind)
        if gating:
            return Availability.CLOSED, reason or "申込の締切が過ぎています"
        # 過ぎていても参加はできる締切。**閉じる根拠にしない。**
        return Availability.UNKNOWN, reason

    end_at = as_utc(end_at)
    if end_at is not None and end_at < now and _ends(opportunity_type):
        return Availability.CLOSED, "開催が終了しています"

    # 締切が未来でも「受付中」とは限らない（満員・中止がある）。
    return Availability.UNKNOWN, None


def _is_past(deadline: datetime, now: datetime, *, date_only: bool) -> bool:
    """締切を過ぎているか。

    **日付しか書かれていなかったものを、当日中に打ち切らない。**
    時刻はこちら側が 00:00 に正規化した値で、出典にあった時刻ではない。
    その日のうちは判断できないものとして残し、翌日以降に過ぎたとする。
    """
    if date_only:
        return deadline.date() < now.date()
    return deadline < now


def _deadline_gates_action(deadline_kind: str | None) -> tuple[bool, str | None]:
    """その締切が、推薦する行動を閉ざすものか。"""
    if deadline_kind is None:
        # 区分を持たなかった頃の行。
        #
        # **当時の prompt がそう指示していたことは、保存された値が申込締切で
        # ある保証にはならない。** 実際、同じ設定で早割の期限を締切として
        # 拾った例が観測されている。
        #
        # それでも閉じるのは、閉じないと期限切れが推薦に戻るため。
        # **確かさが違うことを理由の文面で示し、確認済みのものと混ぜない。**
        return True, "申込の締切が過ぎています（**締切の種類は未確認**）"
    try:
        kind = DeadlineKind(deadline_kind)
    except ValueError:
        return False, "締切の区分が読み取れませんでした"

    if kind in GATING_DEADLINES:
        return True, None
    if kind is DeadlineKind.UNKNOWN:
        return False, "締切が何に対するものか特定できませんでした"
    return False, _NON_GATING_REASON[kind]


_NON_GATING_REASON = {
    DeadlineKind.EARLY_BIRD: "過ぎているのは早割の期限で、参加の締切ではありません",
    DeadlineKind.SPEAKER: "過ぎているのは登壇者募集の締切で、参加の締切ではありません",
    DeadlineKind.OTHER: "過ぎている締切は、参加の締切ではありません",
}


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
