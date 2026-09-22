"""新規ユーザーから一覧・詳細確認までを、アプリだけで動かす（#47）。

**ユーザーの実 DB を使わない。** 実行のたびに独立した DB を作る。
**人手で訂正した 20 件は使わない。** 入力は希望・地域だけ。

計測は 2 つに分ける。

    ① 初回一覧が出るまで（希望の分割 -> 検索専用モデル -> 一覧）
    ② 詳細確認 1 件（本文取得 -> 抽出 -> 突き合わせ -> 訂正）
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
import time
from pathlib import Path

WISHES = (
    "ハウスやテクノなど四つ打ちの音楽を楽しめるイベントに行きたい\n"
    "初めての曲作りにつながるDTM・作曲のワークショップに出たい\n"
    "エンジニアとしてプロダクトを作れるハッカソンに参加したい\n"
    "ポケモンのイベントにも参加したい"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--out", default="../docs/experiments/47-e2e")
    args = ap.parse_args()

    db_path = Path(tempfile.mkdtemp()) / "e2e.db"
    os.environ["DATABASE_URL"] = f"sqlite:///{db_path}"
    os.environ["AGENT_STUB_MODE"] = "false"
    os.environ["SEARCH_ROUTE"] = "discovery"
    os.environ["ORCAROUTER_INCLUDE_COST"] = "true"

    print("=== 条件 ===")
    print(f"  独立した DB: {db_path}（ユーザーの実 DB は使わない）")
    print("  SEARCH_ROUTE=discovery / AGENT_STUB_MODE=false")
    print("  入力は希望と地域だけ。参考20件は渡さない")
    if not args.confirm:
        print("\n--confirm を付けると実行します")
        return 0

    from fastapi.testclient import TestClient

    import models  # noqa: F401  テーブル定義の登録
    from api.deps import PAGE_REQUEST_HEADER_VALUE
    from db.base import Base
    from db.session import engine
    from main import app

    Base.metadata.create_all(bind=engine)
    head = {"X-Requested-With": PAGE_REQUEST_HEADER_VALUE}
    client = TestClient(app)

    # --- 画面入力に相当する操作 ---
    r = client.put(
        "/api/profile",
        json={"name": "検証ユーザー", "wants_now": WISHES, "location": "東京"},
        headers=head,
    )
    print("\nプロフィール保存:", r.status_code)
    if r.status_code != 200:
        print(r.text[:400])
        return 1

    # --- ① 初回一覧が出るまで ---
    t0 = time.monotonic()
    r = client.post("/api/agent/runs", headers=head)
    run_id = (r.json().get("data") or {}).get("run_id")
    print("探索を開始:", r.status_code, run_id)
    status = ""
    while time.monotonic() - t0 < 1800:
        s = client.get(f"/api/agent/runs/{run_id}").json().get("data") or {}
        status = s.get("status", "")
        if status in ("completed", "failed"):
            break
        time.sleep(3)
    list_seconds = round(time.monotonic() - t0, 1)
    print(f"探索 {status} / 一覧までの所要 {list_seconds} 秒")

    run = client.get(f"/api/agent/runs/{run_id}").json().get("data") or {}
    cands = (client.get("/api/opportunities").json().get("data")) or []
    print(f"\n候補 {len(cands)} 件")
    for c in cands:
        print(
            f"  [{c.get('wish') or '-'}] {c['title'][:44]} / "
            f"{(c.get('start_at') or '日付不明')[:10]} / {c.get('location') or '会場不明'} / "
            f"確認済み={c.get('verified')} / 確認項目={c.get('confirmed_fields')}"
        )

    # --- ② 詳細確認 1 件 ---
    detail = None
    detail_seconds = None
    target = next((c for c in cands if c.get("url")), None)
    if target:
        t1 = time.monotonic()
        rr = client.post(
            f"/api/opportunities/{target['opportunity_id']}/detail-check", headers=head
        )
        detail_seconds = round(time.monotonic() - t1, 1)
        detail = (
            (rr.json().get("data") or {}) if rr.status_code == 200 else {"error": rr.text[:300]}
        )
        print(f"\n詳細確認: {rr.status_code} / {detail_seconds} 秒 / {target['title'][:40]}")
        print("  確認できた項目:", detail.get("confirmed_fields"))
        print("  訂正:", json.dumps(detail.get("corrections") or [], ensure_ascii=False)[:400])
        # 連打しても二重に走らないこと
        t2 = time.monotonic()
        client.post(f"/api/opportunities/{target['opportunity_id']}/detail-check", headers=head)
        print(f"  もう一度押した場合: {round(time.monotonic() - t2, 1)} 秒（取り直さない）")

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    (out_dir / f"{stamp}.json").write_text(
        json.dumps(
            {
                "list_seconds": list_seconds,
                "detail_seconds": detail_seconds,
                "run": run,
                "candidates": cands,
                "detail": detail,
            },
            ensure_ascii=False,
            indent=1,
            default=str,
        )
    )
    print(f"\n書き出し: {out_dir / f'{stamp}.json'}")
    print(
        "run の費用記録:",
        json.dumps(run.get("usage") or run.get("usage_json") or {}, ensure_ascii=False)[:300],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
