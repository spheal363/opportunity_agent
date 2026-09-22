"""不足している希望だけ、追加で探す（#47）。**最初からやり直さない。**

既に持っている候補名を渡して重複を避ける。
**参考20件は供給源にしない。** 渡すのは今回自分で見つけた名前だけ。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from scripts._experiment import apply_recording_settings

apply_recording_settings()

import httpx  # noqa: E402

from scripts.orca_search_model import (  # noqa: E402
    FIVE_RULES,
    RULES,
    WISHES,
    call,
    settled,
    verdict,
)


def prompt(wish_text: str, window: str, known: list[str], want: int) -> str:
    dup = ("\n".join(f"  - {k}" for k in known)) or "  （なし）"
    return (
        f"【希望】{wish_text}\n"
        f"【地域】東京都内で現地参加できるもの。オンラインのみは対象外。\n"
        f"【期間】{window}\n\n"
        f"**次はすでに把握しているので、挙げないでください:**\n{dup}\n\n"
        f"これら以外で、この希望に合う**日程のある具体的な企画**を {want} 件挙げてください。\n"
        f"各件について イベント名 / 開催日 / 東京都内の会場 / 1 行の説明 / 情報源URL。\n"
        f"**開催日・会場は出典に書かれている文字列のまま**書いてください。\n"
        f"出典に無い区名や住所を足さないでください。会場が未発表なら「未発表」と書いてください。\n"
        f"過去の回のページを今年の回として扱わないでください。開催年を確認してください。\n\n"
        f"{RULES}{FIVE_RULES}"
    )


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--round", type=int, required=True)
    ap.add_argument("--wishes", required=True, help="カンマ区切り")
    ap.add_argument("--known", required=True, help="既知の候補名 JSON ファイル")
    ap.add_argument("--want", type=int, default=5)
    ap.add_argument("--model", default="openai/gpt-5-search-api")
    ap.add_argument("--max-tokens", type=int, default=4000)
    args = ap.parse_args()

    from ai import window as w

    win = w.for_now()
    window = f"{win.start:%Y年%m月%d日}〜{win.end:%Y年%m月%d日}"
    known = json.loads(Path(args.known).read_text())
    targets = [x.strip() for x in args.wishes.split(",") if x.strip()]
    print(f"=== 追加探索 第{args.round}巡 / {targets} / 各 {args.want} 件 ===")
    if not args.confirm:
        return 0

    out_dir = Path(f"../docs/experiments/47-search-model/extra-round{args.round}")
    out_dir.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    with httpx.Client(timeout=600) as client:
        jobs = [(k, prompt(WISHES[k], window, known.get(k, []), args.want)) for k in targets]
        with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
            futs = [ex.submit(call, client, args.model, p, args.max_tokens) for _, p in jobs]
            res = [f.result() for f in futs]
    total = 0.0
    for (label, _), r in zip(jobs, res, strict=True):
        r["label"] = label
        r["verdict"] = verdict(r)
        r["cost_usd_settled"] = settled(r.get("request_id") or "")
        total += r["cost_usd_settled"] or 0
        (out_dir / f"{label.replace('/', '_')}.json").write_text(
            json.dumps(r, ensure_ascii=False, indent=1)
        )
        print(
            f"  {label}: {r['verdict']} / 本文 {r.get('content_len', 0)}字 "
            f"/ 引用 {len(r.get('annotations') or [])} "
            f"/ ${r['cost_usd_settled']} / {r['seconds']}秒"
        )
    print(
        f"\n第{args.round}巡: 実経過 {round(time.monotonic() - t0, 1)} 秒 / 実費 ${round(total, 6)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
