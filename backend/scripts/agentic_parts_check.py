"""試作 v2 の部品検証（#47）。**既知の URL を使う。発見性能には数えない。**

確かめること:

1. 台帳が **企画数と日程数を分けて**数え、同じ企画の別日程をまとめること
2. 本文を**全文保存**し、cursor で続きを読めること（切って失わない）
3. 一覧ページ 1 枚から、モデルが**複数の候補**を取り出せること
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from scripts._experiment import apply_recording_settings

apply_recording_settings()

import httpx  # noqa: E402

from ai import cost  # noqa: E402
from ai.llm import untrusted_block  # noqa: E402
from scripts.agentic_explore import (  # noqa: E402
    DISCOVER_SYSTEM,
    DISCOVER_TOOLS,
    PAGE_CHARS,
    Budget,
    Ledger,
    Pages,
    _call,
)

OK, NG = "OK", "**失敗**"


def check_ledger() -> bool:
    led = Ledger()
    led.add(
        wish="音楽", name="Aパーティー", source_url="https://example.test/a", dates=["2026-10-03"]
    )
    # 同じ企画を別の出典から、別日程で
    v, _ = led.add(
        wish="音楽", name="A パーティー", source_url="https://other.test/a", dates=["2026-10-17"]
    )
    led.add(
        wish="ポケモン",
        name="B展",
        source_url="https://example.test/b",
        dates=["2026-10-10", "2026-10-11"],
    )
    led.add(wish="ハッカソン", name="C", source_url="https://example.test/c")  # 日程未取得
    bad, _ = led.add(wish="音楽", name="", source_url="https://example.test/x")

    results = [
        ("同じ企画を 1 行にまとめる", led.programs() == 3, f"企画 {led.programs()} 件"),
        ("別日程を足す", v == "日程を追加", v),
        ("日程を分けて数える", led.dates_count() == 5, f"日程 {led.dates_count()} 件"),
        ("日程未取得も 1 日程として数える", led.by_wish()["ハッカソン"]["日程"] == 1, ""),
        ("名前が空なら却下", bad == "却下", bad),
        (
            "足りない希望を出す",
            set(led.missing()) == {"音楽", "DTM・作曲", "ハッカソン", "ポケモン"},
            str(led.missing()),
        ),
    ]
    ok = True
    for name, passed, detail in results:
        print(f"  {OK if passed else NG}  {name}  {detail}")
        ok &= passed
    return ok


def check_pages(run_dir: Path) -> bool:
    """**一覧ページを全文保存し、続きを読めるか。**"""
    url = "https://z-maruyama.jp/ja/night"  # 既知の会場スケジュール
    pages = Pages(run_dir)
    first = pages.read(url, 0)
    if "取得できませんでした" in first:
        print(f"  {NG}  一覧の取得: {first[:80]}")
        return False
    total = len(pages.full[url])
    second = pages.read(url, PAGE_CHARS)
    saved = list((run_dir / "pages").glob("*.txt"))
    checks = [
        (
            "全文をディスクへ保存",
            len(saved) == 1 and saved[0].stat().st_size > total,
            f"{total} 字",
        ),
        (
            "1 回目は先頭を渡す",
            f"ここまで {PAGE_CHARS}/{total}" in first or total <= PAGE_CHARS,
            "",
        ),
        (
            "cursor で続きを読める",
            len(second) > 100 and second != first,
            f"2 回目 {len(second)} 字",
        ),
        (
            "渡した範囲を記録",
            len(pages.served) == 2 and pages.served[1]["cursor"] == PAGE_CHARS,
            "",
        ),
    ]
    ok = True
    for name, passed, detail in checks:
        print(f"  {OK if passed else NG}  {name}  {detail}")
        ok &= passed
    return ok


def check_listing_expansion(model: str, run_dir: Path) -> bool:
    """**一覧 1 枚から複数候補を取り出せるか。** ここだけ LLM を呼ぶ。"""
    url = "https://z-maruyama.jp/ja/night"
    pages = Pages(run_dir / "llm")
    body = pages.read(url, 0)
    led = Ledger()
    budget = Budget()
    messages = [
        {"role": "system", "content": DISCOVER_SYSTEM},
        {
            "role": "user",
            "content": untrusted_block(
                "user_request",
                "やってみたいこと:\n"
                "- ハウスやテクノなど四つ打ちの音楽を楽しめるイベントに行きたい\n"
                "活動地域: 東京。現地参加できるもの。\n"
                "対象期間: 2026年09月22日〜2026年11月21日\n\n"
                "次のページを読み、載っている個別の催しを "
                "add_candidates でまとめて登録してください。",
            ),
        },
        {"role": "user", "content": body},
    ]
    with httpx.Client(timeout=240) as client, cost.track() as tracker:
        msg = _call(client, model, messages, DISCOVER_TOOLS, budget)
    added = 0
    for call in msg.get("tool_calls") or []:
        if call["function"]["name"] != "add_candidates":
            continue
        args = json.loads(call["function"]["arguments"] or "{}")
        for c in args.get("candidates") or []:
            verdict, _ = led.add(
                wish=c.get("wish", ""),
                name=c.get("name", ""),
                source_url=c.get("source_url", ""),
                dates=c.get("dates"),
                venue=c.get("venue"),
                region=c.get("region"),
                found_via=c.get("found_via"),
            )
            added += verdict in ("登録", "日程を追加")
    for e in led.entries.values():
        print(f"      - {e.name[:46]} / {e.dates or '日程なし'} / {e.venue or '会場なし'}")
    passed = led.programs() >= 3
    print(
        f"  {OK if passed else NG}  一覧 1 枚から複数候補  企画 {led.programs()} 件 / "
        f"日程 {led.dates_count()} 件 / 実費 ${budget.usd:.4f} / req {len(tracker.request_ids)}"
    )
    return passed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="anthropic/claude-opus-4.7")
    ap.add_argument("--out", default="../docs/experiments/47-agentic-v2/parts-check")
    ap.add_argument("--with-llm", action="store_true", help="一覧展開の検証（LLM を 1 回呼ぶ）")
    args = ap.parse_args()
    run_dir = Path(args.out)
    run_dir.mkdir(parents=True, exist_ok=True)

    print("1. 候補台帳")
    ok = check_ledger()
    print("\n2. 本文の保存と続き読み（既知の会場スケジュール）")
    ok &= check_pages(run_dir)
    if args.with_llm:
        print("\n3. 一覧 1 枚からの複数候補（LLM を 1 回）")
        ok &= check_listing_expansion(args.model, run_dir)
    else:
        print("\n3. 一覧展開の検証は --with-llm を付けると実行します")
    print("\n結果:", "全て OK" if ok else "**失敗あり**")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
