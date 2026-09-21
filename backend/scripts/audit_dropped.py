"""C が読まなかった候補を、後から確認する（取りこぼし監査）。

    .venv/bin/python -m scripts.audit_dropped <C の実験ディレクトリ>
    .venv/bin/python -m scripts.audit_dropped <C の実験ディレクトリ> --confirm

## なぜ要るか

**C の取りこぼしは、C が実際に捨てた候補を見ないと測れない。**
A の検索結果と突き合わせても、C 固有の取りこぼしは分からない。
A と C では検索サービスが違い、候補そのものが違うため。

## 費用と時間は C の実行とは別に数える

監査は**通常の探索には含まれない**追加作業。ここでかかった本文取得と
LLM の費用・時間を、C の実行費用・時間に混ぜない。

## 完全には評価できない

上限の範囲でしか確認しないので、**本文を見ない候補が残る。**
残った件数を明示する。
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

# **実費を取る。** 前回これを設定しておらず、監査の費用が全件「不明」になった。
# 見積もりしか残らないと、C の費用と並べて語れない。
os.environ.setdefault("ORCAROUTER_INCLUDE_COST", "true")
from datetime import UTC, date, datetime
from pathlib import Path

from ai import availability, cost, evidence
from ai.extraction import extract_opportunity
from ai.llm import LLMError
from config import get_settings
from tools import registry
from tools.search.base import SearchError

# 監査で確認する上限。**無制限には増やさない。**
MAX_AUDIT = 10
TODAY = date(2026, 9, 21)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--limit", type=int, default=MAX_AUDIT)
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    directory = Path(args.directory).resolve()
    run = json.loads((directory / "run.json").read_text())
    prefilter = run.get("prefilter")
    if not prefilter:
        print("粗選別の記録がありません（構成 C の run を指定してください）。")
        return 1

    deferred = prefilter["deferred"][: args.limit]
    remaining = len(prefilter["deferred"]) - len(deferred)

    print("=== 取りこぼし監査の計画（**C の実行費用とは別に数える**）===")
    print(f"  C が見つけた候補   {prefilter['total']} 件")
    print(f"  C が読んだ候補     {len(prefilter['read'])} 件")
    print(f"  C が読まなかった   {len(prefilter['deferred'])} 件")
    print(f"  今回確認する       {len(deferred)} 件（上限 {args.limit}）")
    if remaining:
        print(f"  **本文を見ない候補が {remaining} 件残る。取りこぼしを完全には評価できない。**")
    print("  本文取得 1 回 + LLM 抽出 1 回 / 件。Retry は本番と同じ上限")
    print()
    if not args.confirm:
        print("実行するには --confirm を付けてください。**まだ API を呼んでいません。**")
        return 0
    if not get_settings().orcarouter_api_key:
        print("ORCAROUTER_API_KEY が未設定です。")
        return 1

    started = time.perf_counter()
    with cost.track() as tracker, cost.step("audit"):
        results = [_one(c) for c in deferred]
    elapsed_ms = int((time.perf_counter() - started) * 1000)

    payload = {
        "at": datetime.now(UTC).isoformat(),
        "source_run": run["run_id"],
        "note": "**C の実行には含まれない追加作業。** 費用・時間を混ぜない",
        "audited": len(deferred),
        "not_audited": remaining,
        "elapsed_ms": elapsed_ms,
        "usage": tracker.to_dict(),
        "results": results,
    }
    (directory / "audit-dropped.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    _report(payload)
    return 0


def _one(candidate: dict) -> dict:
    """1 件を取りに行って抽出する。**失敗は失敗として残す。**"""
    url = candidate["url"]
    started = time.perf_counter()
    try:
        out = registry.invoke("read_page", url=[url]).data
    except SearchError as exc:
        return {**candidate, "error": f"本文取得に失敗: {exc}"}

    pages = out["pages"]
    if not pages:
        return {**candidate, "error": "本文を取得できませんでした"}

    page = pages[0]
    try:
        item = extract_opportunity(
            url, page.content, today=TODAY, source_title=page.title or candidate["title"]
        )
    except LLMError as exc:
        return {**candidate, "error": f"抽出に失敗: {exc}"}

    grounded = evidence.ground_deadline_kind(item, page.content)
    status, reason = availability.from_dates(
        opportunity_type=grounded.type,
        deadline=grounded.deadline,
        end_at=grounded.end_at,
        deadline_kind=grounded.deadline_kind,
        deadline_is_date_only=grounded.deadline_is_date_only,
        speaker_is_the_opportunity=evidence.is_a_call_for_speakers(
            grounded.title, grounded.description
        ),
    )
    return {
        **candidate,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "extracted": grounded.model_dump(mode="json"),
        "availability": str(status),
        "availability_reason": reason,
    }


def _report(payload: dict) -> None:
    usage = payload["usage"]
    print("=== 監査の結果 ===")
    print(f"  確認した {payload['audited']} 件  所要 {payload['elapsed_ms'] / 1000:.1f} 秒")
    if payload["not_audited"]:
        print(f"  **未確認 {payload['not_audited']} 件。取りこぼしを完全には評価できない。**")
    print(f"  本文取得 {usage.get('extract_calls', 0)} 件")
    print(
        f"  実費 ${usage.get('actual_usd', 0):.6f}"
        f"（実費不明 {usage.get('responses_without_actual_cost', 0)} 件）"
    )
    print("  **この費用と時間は C の実行には含めない。**")
    print()
    for r in payload["results"]:
        if "error" in r:
            print(f"  x {r['title'][:44]:46} {r['error']}")
            continue
        e = r["extracted"]
        print(f"  - {e['title'][:44]:46} type={e['type']:12} {r['availability']}")
        print(f"      {r['url'][:78]}")
    print()
    print("  **有望かどうかは点数では決めない。** 目標とのつながり、受付状況の根拠、")
    print("  重複、普段探さない度合い、次に取れる行動で人が確認する。")


if __name__ == "__main__":
    sys.exit(main())
