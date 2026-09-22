"""保存済み run の候補を評価する（#47）。**新しい Web 探索はしない。**

表示変更の確認のために、すでにある候補へ評価だけを付ける。
時間と費用は**検索とは別に**記録する。
"""

from __future__ import annotations

import argparse
import sys
import time

from scripts._experiment import apply_recording_settings

apply_recording_settings()

from ai import cost, matching  # noqa: E402
from db.session import SessionLocal  # noqa: E402
from models.agent_run import AgentRun  # noqa: E402
from models.opportunity import Opportunity  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_id")
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    db = SessionLocal()
    run = db.get(AgentRun, args.run_id)
    if run is None or not run.selected_ids:
        print("その run の候補が見つかりません")
        return 1
    rows = [db.get(Opportunity, i) for i in run.selected_ids]
    rows = [r for r in rows if r is not None and matching.recommendable(r)]
    # **現在のプロフィールで補わない。** 原文が無い古い run は、
    # その run の実行時に保存された分析結果（wanted_now）を使う。
    wishes = run.wishes_source
    source = "入力原文"
    if not wishes:
        wishes = "\n".join((run.goal_analysis or {}).get("wanted_now") or [])
        source = "**原文は未保存。** run 実行時の分析結果（wanted_now）を使用"
    print(f"評価対象 {len(rows)} 件 / 希望の出どころ: {source}")
    if not wishes:
        print("希望が分からないので評価しません（現在のプロフィールでは補いません）")
        return 1
    if not args.confirm:
        print("--confirm を付けると実行します")
        return 0

    win = run.search_window or {}
    window = f"{win.get('start')}〜{win.get('end')}" if win else None
    t0 = time.monotonic()
    with cost.track() as tracker:
        judged = matching.judge(
            rows,
            wishes=wishes,
            region=run.region_source,
            window=window,
        )
    secs = round(time.monotonic() - t0, 1)
    if not judged:
        print("**評価できませんでした。** 架空の点は付けません")
        return 1

    for r in rows:
        j = judged.get(r.opportunity_id)
        if j is None:
            continue
        r.evaluated = True
        r.score = j.match
        r.reason = j.reason
        r.match_reasons = list(j.matched_wishes)
        r.unknowns = list(j.unknowns)
    top = matching.order(rows, judged, limit=3)
    top_ids = [r.opportunity_id for r in top]
    run.selected_ids = top_ids + [i for i in run.selected_ids if i not in top_ids]
    run.recommended_count = len(top_ids)
    db.commit()

    print(f"\n評価 {len(judged)} 件 / おすすめ {len(top_ids)} 件 / {secs} 秒")
    print(f"実費 ${tracker.actual_usd:.6f} / 実費不明 {tracker.responses_without_actual_cost} 件")
    print("\n--- おすすめ ---")
    for r in top:
        j = judged[r.opportunity_id]
        print(f"  [{j.match}] {r.title[:44]}")
        print(f"       希望: {' / '.join(j.matched_wishes)[:80]}")
        print(f"       理由: {j.reason[:110]}")
        if j.unknowns:
            print(f"       未確認: {' / '.join(j.unknowns)[:80]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
