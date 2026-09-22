"""探索の対象期間（#47）。

**「今後 60 日」を run の開始時に確定する。** 実行中に日付が変わっても
基準日をずらさない。探索は 2 分ほどかかり、深夜に走らせると途中で
「今日」が変わる。ずれると、同じ run の中で期間内だった候補が期間外になる。

    run 開始  ->  SearchWindow を確定  ->  検索計画へ日付範囲を渡す
                                      ->  取得後の候補を分類する

## 期間で判定しないもの

**コミュニティ・求人・通年募集に、イベントの開催期間を機械的に当てない。**
「毎月開催のコミュニティ」に開催日が入っていなくても、それは期間外ではない。
種別で分ける（`_TIME_BOUND`）。

## 推測で期間内に入れない

日時が取れていない候補を「たぶん期間内」として並べない。
`SCHEDULE_UNKNOWN` として、期間内の候補とは分けて見せる。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from enum import StrEnum
from zoneinfo import ZoneInfo

from schemas.opportunity import OpportunityType

# 既定の探索期間。**仮説であって正解ではない。** 画面から変えられる。
DEFAULT_WINDOW_DAYS = 60
MIN_WINDOW_DAYS = 7
MAX_WINDOW_DAYS = 365

# 利用者のタイムゾーンの既定。日本向けのため JST。
DEFAULT_TIMEZONE = "Asia/Tokyo"


class WindowStatus(StrEnum):
    """候補と探索期間の関係。**「期間外」と「分からない」を混ぜない。**"""

    # 開催日時が期間の中にある
    IN_WINDOW = "in_window"
    # 開催日時が期間より先。締切が近いものはここに入る（別扱いにする）
    AFTER_WINDOW = "after_window"
    # 開催が終わっている
    ENDED = "ended"
    # 開催日時が取れていない。**推測で期間内に入れない**
    SCHEDULE_UNKNOWN = "schedule_unknown"
    # 期間の概念が当てはまらない種別（コミュニティ・求人・通年募集）
    NOT_TIME_BOUND = "not_time_bound"


# 開催日が 1 点に決まる種別。ここに無いものへ開催期間を当てない。
_TIME_BOUND = frozenset(
    {
        OpportunityType.EVENT,
        OpportunityType.HACKATHON,
        OpportunityType.COMPETITION,
    }
)


@dataclass(frozen=True)
class SearchWindow:
    """この run が対象にする期間。**run の開始時に確定する。**"""

    start: date
    end: date
    timezone: str = DEFAULT_TIMEZONE

    @property
    def days(self) -> int:
        return (self.end - self.start).days

    def to_dict(self) -> dict:
        return {"start": self.start.isoformat(), "end": self.end.isoformat(), "tz": self.timezone}

    @classmethod
    def from_dict(cls, raw: dict | None) -> SearchWindow | None:
        if not raw:
            return None
        try:
            return cls(
                start=date.fromisoformat(raw["start"]),
                end=date.fromisoformat(raw["end"]),
                timezone=raw.get("tz", DEFAULT_TIMEZONE),
            )
        except (KeyError, TypeError, ValueError):
            # 古い run の記録。**無いものとして扱い、run を落とさない。**
            return None


def for_now(*, days: int = DEFAULT_WINDOW_DAYS, timezone: str = DEFAULT_TIMEZONE) -> SearchWindow:
    """いまこの瞬間の「今日から N 日先まで」。

    **利用者のタイムゾーンの今日**を使う。UTC の今日だと、日本の朝 9 時前に
    走らせたとき前日から数えることになる。
    """
    days = max(MIN_WINDOW_DAYS, min(MAX_WINDOW_DAYS, days))
    try:
        today = datetime.now(ZoneInfo(timezone)).date()
    except Exception:
        # 知らないタイムゾーン名で run を落とさない。既定へ戻す。
        timezone = DEFAULT_TIMEZONE
        today = datetime.now(ZoneInfo(DEFAULT_TIMEZONE)).date()
    return SearchWindow(start=today, end=today + timedelta(days=days), timezone=timezone)


def classify(
    *,
    opportunity_type: str | None,
    start_at: datetime | None,
    end_at: datetime | None,
    window: SearchWindow,
) -> WindowStatus:
    """候補が期間に入るか。**受付中かどうかはここでは見ない。**

    受付状況は `ai/availability.py` が別に判定する。混ぜると、
    「期間内だが申込が締め切られた」候補を表せなくなる。

    日付だけの情報は、その日のうちに入っていれば期間内とする
    （時刻が無いことを理由に落とさない）。
    """
    if opportunity_type not in _TIME_BOUND:
        # コミュニティ・求人・奨学金・アクセラレーターなど。
        # **開催日が無くても期間外ではない。**
        return WindowStatus.NOT_TIME_BOUND

    if start_at is None and end_at is None:
        return WindowStatus.SCHEDULE_UNKNOWN

    # 終わりが分かっているならそれで、無ければ開始で終了を判断する。
    finish = _as_date(end_at or start_at, window.timezone)
    if finish is not None and finish < window.start:
        return WindowStatus.ENDED

    begin = _as_date(start_at or end_at, window.timezone)
    if begin is None:
        return WindowStatus.SCHEDULE_UNKNOWN
    if begin > window.end:
        return WindowStatus.AFTER_WINDOW
    return WindowStatus.IN_WINDOW


def _as_date(value: datetime | None, timezone: str) -> date | None:
    """**利用者のタイムゾーンの日付**に直す。

    DB の値は UTC（SQLite は tz を保持しないので naive は UTC とみなす）。
    UTC のまま比較すると、日本時間 9 時開始の催しが前日扱いになる。
    """
    if value is None:
        return None
    aware = value if value.tzinfo else value.replace(tzinfo=UTC)
    try:
        return aware.astimezone(ZoneInfo(timezone)).date()
    except Exception:
        return aware.astimezone(ZoneInfo(DEFAULT_TIMEZONE)).date()


def label(status: WindowStatus, window: SearchWindow) -> str:
    """画面と Log に出す一行。**対象種別と期間条件の関係を言う。**"""
    return {
        WindowStatus.IN_WINDOW: f"{window.start:%Y/%m/%d}〜{window.end:%Y/%m/%d} に開催",
        WindowStatus.AFTER_WINDOW: f"{window.end:%Y/%m/%d} より先の開催",
        WindowStatus.ENDED: "開催が終了",
        WindowStatus.SCHEDULE_UNKNOWN: "日程未確認",
        WindowStatus.NOT_TIME_BOUND: "通年・随時（開催期間の条件を当てない）",
    }[status]
