"""ユーザーが選んだ候補だけを、出典で確かめる（#47）。

**一覧の全件には行わない。** 一覧は「検索で見つかった候補」であって未確認。
ここで初めて Jina で本文を取り、抽出して突き合わせる。

## 守ること

- **取得できないことを誤りと決めつけない。** 未確認として残す。
- **訂正は上書きせず履歴に積む。** 検索時の値は `searched_values` に残したまま。
- **`verified=True` だけで全項目が確認済みに見せない。**
  実際に確認できた項目だけ `confirmed_fields` に入れる。
- **同じ候補への連打で二重に走らせない。**
- 参加資格は「出典に記載があるか」であって、**本人が満たすかの照合ではない。**
"""

from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from ai import cost, extraction, guard, interstitial
from logging_config import get_logger
from models.opportunity import Opportunity
from tools import registry

logger = get_logger(__name__)

# **日付は現地（Asia/Tokyo）で比べる。**
# UTC のまま `.date()` を取ると、JST 9/26 00:00 が 9/25 に見え、
# 直っていないのに「9/26 -> 9/25 に訂正」と表示された（ブラウザで確認して判明）。
JST = ZoneInfo("Asia/Tokyo")


def _local_date(v: datetime | None):
    return None if v is None else _as_utc(v).astimezone(JST).date()


# 直近に確認済みならやり直さない（連打対策）。
RECHECK_AFTER_SECONDS = 300


class DetailUnavailable(Exception):
    """出典を取得できなかった。**誤りという意味ではない。**"""


def _as_utc(v: datetime | None) -> datetime | None:
    if v is None:
        return None
    return v if v.tzinfo else v.replace(tzinfo=UTC)


def _fresh(row: Opportunity) -> bool:
    if row.detail_checked_at is None:
        return False
    age = (datetime.now(UTC) - _as_utc(row.detail_checked_at)).total_seconds()
    return age < RECHECK_AFTER_SECONDS


def _note(row: Opportunity, field: str, before, after, source: str) -> None:
    """**履歴に積む。上書きしない。**"""
    row.corrections = list(row.corrections or []) + [
        {
            "field": field,
            "before": None if before is None else str(before),
            "after": None if after is None else str(after),
            "source": source,
            "checked_at": datetime.now(UTC).isoformat(),
        }
    ]


def _on_page(url: str, body: str) -> bool:
    """その URL が本文に実在するか。**組み立てた URL を受け入れないため。**"""
    return bool(url) and url.split("?")[0].rstrip("/") in body


def _confirm(row: Opportunity, field: str) -> None:
    if field not in (row.confirmed_fields or []):
        row.confirmed_fields = list(row.confirmed_fields or []) + [field]


def check_detail(db: Session, opportunity_id: str, user_id: str) -> Opportunity | None:
    """1 件だけ確認する。**すでに確認済みならそのまま返す（連打対策）。**"""
    row = db.get(Opportunity, opportunity_id)
    if row is None or row.user_id != user_id:
        return None
    if _fresh(row):
        logger.info("detail.skip_recent id=%s", opportunity_id)
        return row
    if not row.url:
        row.detail_checked_at = datetime.now(UTC)
        row.availability_reason = "出典 URL が無いため確認できません"
        db.commit()
        return row

    try:
        pages = registry.invoke("read_page", url=row.url).data["pages"]
    except Exception as exc:  # noqa: BLE001
        logger.info("detail.fetch_failed id=%s kind=%s", opportunity_id, type(exc).__name__)
        pages = []
    body = pages[0].content if pages else ""
    why = (
        interstitial.looks_like_interstitial(title=pages[0].title, content=body)
        if pages
        else "本文を取得できませんでした"
    )
    if not body or why:
        # **未確認のまま残す。誤りにしない。**
        row.detail_checked_at = datetime.now(UTC)
        row.availability_reason = f"出典を取得できませんでした（{why or '本文が空'}）"
        db.commit()
        return row

    checked = guard.inspect(body)
    # **初回探索とは別の費用として追えるようにする。**
    with cost.track() as tracker:
        cost.record_extract(1)
        cost.record_extract_success(1)
        item = extraction.extract_opportunity(row.url, checked.text, source_title=row.title)

    before_start = row.start_at
    # --- 日付 ---
    if item.start_at is not None:
        new = _as_utc(item.start_at)
        old = _as_utc(row.start_at)
        if _local_date(old) != _local_date(new):
            _note(row, "start_at", _local_date(old), _local_date(new), row.url)
        row.start_at = new
        row.start_at_is_date_only = item.start_at_is_date_only
        _confirm(row, "start_at")
    if item.end_at is not None:
        new_end = _as_utc(item.end_at)
        old_end = _as_utc(row.end_at)
        if _local_date(old_end) != _local_date(new_end):
            _note(row, "end_at", _local_date(old_end), _local_date(new_end), row.url)
        row.end_at = new_end
        row.end_at_is_date_only = item.end_at_is_date_only
        _confirm(row, "end_at")

    # --- 会場・地域 ---
    if item.location:
        if (row.location or "") != item.location:
            _note(row, "location", row.location, item.location, row.url)
        row.location = item.location
        _confirm(row, "location")
    if item.region:
        if (row.region or "") != item.region:
            _note(row, "region", row.region, item.region, row.url)
        row.region = item.region
        _confirm(row, "region")
    if item.format is not None:
        row.format = item.format.value
        row.online_participation = item.online_participation

    # --- 受付・参加資格。**確認できたものだけ。** ---
    if item.deadline is not None:
        row.deadline = _as_utc(item.deadline)
        row.deadline_kind = item.deadline_kind.value
        row.deadline_quote = item.deadline_quote
        row.deadline_is_date_only = item.deadline_is_date_only
        _confirm(row, "deadline")
    if item.eligibility:
        row.eligibility = item.eligibility
        # **記載を確認しただけ。本人が満たすかの照合ではない。**
        _confirm(row, "eligibility_stated")
    if item.cost is not None:
        row.cost = item.cost
        row.cost_kind = item.cost_kind.value
        _confirm(row, "cost")
    # 申込先。**URL が取得元と違うかどうかは根拠にならない。**
    #
    # 以前は `item.url != row.url` だけで「申込先を確認した」としていた。
    # これは **別 URL というだけ**で、その導線がこの候補のものだとは言えない。
    #
    # いま言えるのは「その URL が出典ページの本文に実在する」ことまで。
    # **それが申込先かどうかは未確認**なので、`url_is_source_only` は倒さない。
    if item.url and _on_page(item.url, checked.text):
        row.application_url = item.url
        _confirm(row, "application_url_on_page")

    # **日付が変わったら期間判定も変わる。**
    # `window_status` は列ではなく応答時に算出される項目なので、
    # ここでは start_at / end_at を直せば並び順も期間表示も追従する。
    if row.start_at is not None and row.start_at != before_start:
        _confirm(row, "window_recomputed")

    # 本文取得は Jina Reader（鍵なしの無料枠）。**利用料は $0。回数だけ残す。**
    row.detail_usage = {
        **tracker.to_dict(),
        "page_fetches": 1,
        "page_fetch_service": "jina-reader（鍵なし・無料枠 / 利用料 $0）",
    }
    row.verified = True
    row.verified_at = datetime.now(UTC)
    row.verification_source = row.url
    row.detail_checked_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    logger.info(
        "detail.checked id=%s confirmed=%s corrections=%d",
        opportunity_id,
        ",".join(row.confirmed_fields or []) or "-",
        len(row.corrections or []),
    )
    return row
