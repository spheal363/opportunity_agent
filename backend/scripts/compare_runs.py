"""A と C の run を、**公平に**並べる（#65）。API は呼ばない。

    .venv/bin/python -m scripts.compare_runs <A の dir> <C の dir>

## 共有した検索計画の扱い

計画は片方の run で 1 度だけ生成し、もう片方は読み込んだ。そのままでは
**生成した側だけが費用と時間を負う。**

  構成ごとの比較   両方に計画生成を**同じ条件で**足す
  実際に払った額   共有ぶんは**1 度だけ**数える

## 工程別時間と全体時間

各工程の時間は**その工程に入ってから出るまで**の経過時間で、
**中の並列呼び出しを含む。** 工程どうしは直列なので、合計は全体に近い。
差は工程の外（DB 書き込み、ログ）。

## 削減率は 2 つに分ける

  OrcaRouter だけ   LLM の実費で比べられる
  総費用            検索・本文取得の単価が**未確認**なので出せない
"""

from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> int:
    a = _load(sys.argv[1])
    c = _load(sys.argv[2])
    shared = _shared_plan(a, c)

    print("=== 共有した検索計画 ===")
    for name, run in (("A", a), ("C", c)):
        sp = run["run"]["search_plan"]
        print(f"  {name}: {sp['source']}")
    if shared:
        print(f"  生成: {shared['ms'] / 1000:.1f} 秒 / 実費 ${shared['usd']:.6f}")
        print("  **いま生成した側の合計に入っている。** 下の表では両方に足す。")
    print()

    print("=== ① 構成ごとの比較（計画生成を両方に同じ条件で含む）===")
    print(f"  {'':24} {'A':>18} {'C':>18}")
    for label, fa, fc in _rows(a, c, shared):
        print(f"  {label:24} {fa:>18} {fc:>18}")
    print()

    print("=== ② 今回実際に払った実験総額（共有ぶんは 1 度だけ）===")
    paid = a["actual_usd"] + c["actual_usd"]
    print(f"  OrcaRouter 実費 ${paid:.6f}（A ${a['actual_usd']:.6f} + C ${c['actual_usd']:.6f}）")
    print("  **共有ぶんは A の中に 1 度だけ含まれる。二重には数えない。**")
    print(
        f"  Jev ${c['jev_usd']:.6f}（推定）/ Serper 無料枠 {c['search']} クエリ"
        f" / Jina 支払い $0（{c['fetch_ok']}/{c['fetch']} 件取得）"
    )
    print(f"  Tavily {a['search']} 検索 + {a['fetch']} 本文取得 **単価・残量とも未確認**")
    print()

    print("=== ③ 削減率（**分けて示す**）===")
    la, lc = _with_shared(a, c, shared)
    cut = (la - lc) / la * 100
    word = "削減" if cut > 0 else "増加"
    print(f"  OrcaRouter の実費  {abs(cut):.0f}% {word}（${la:.6f} -> ${lc:.6f}）")
    print("  **1 run ずつの値。** 出力長は実行ごとに変わるので、率は確定ではない。")
    print("  総費用             **出せない**。検索・本文取得の単価が未確認で、")
    print("                     Serper と Jina は今回無料枠のため支払いが 0 だった。")
    print("                     継続利用時の単価が分からない限り、総額は比べられない。")
    print()

    print("=== ④ 工程別時間と全体時間 ===")
    print("  **各工程は中の並列呼び出しを含む経過時間。** 工程どうしは直列。")
    steps = sorted(set(a["steps"]) | set(c["steps"]))
    print(f"  {'工程':18} {'A':>10} {'C':>10}")
    for s in steps:
        print(f"  {s:18} {a['steps'].get(s, 0) / 1000:9.1f}s {c['steps'].get(s, 0) / 1000:9.1f}s")
    for name, run in (("A", a), ("C", c)):
        total = run["total_ms"] / 1000
        summed = sum(run["steps"].values()) / 1000
        print(
            f"  {name}: 工程の合計 {summed:.1f}s / 全体 {total:.1f}s "
            f"（差 {total - summed:.1f}s は工程の外）"
        )
    print("  **この節は共有ぶんを足していない実測値。** ① の表とは前提が違う。")
    return 0


def _load(path: str) -> dict:
    run = json.loads((Path(path) / "run.json").read_text())
    u = run["usage"]
    by = u["by_step"]
    return {
        "run": run,
        "total_ms": run["total_ms"],
        "steps": {k: v.get("elapsed_ms", 0) for k, v in by.items()},
        "actual_usd": u["actual_usd"],
        "unknown_cost": u["responses_without_actual_cost"],
        "requests": sum(v["request_attempts"] for v in by.values()),
        "jev_usd": sum(v.get("jev", {}).get("usd", 0.0) for v in by.values()),
        "jev_requests": sum(v.get("jev", {}).get("request_attempts", 0) for v in by.values()),
        "search": u["search_calls"],
        "fetch": u["extract_calls"],
        "fetch_ok": u.get("extract_successes", 0),
        "candidates": len(run["opportunities"]),
    }


def _shared_plan(a: dict, c: dict) -> dict | None:
    """計画を生成した側から、その 1 回分を取り出す。"""
    for run in (a["run"], c["run"]):
        if run["search_plan"]["source"] and "生成" in run["search_plan"]["source"]:
            call = next(
                (x for x in run["llm_calls"] if x["step"] == "search_plan" and x.get("usage")),
                None,
            )
            if call is None:
                return None
            return {"ms": call["elapsed_ms"], "usd": _usd(run, call)}
    return None


def _usd(run: dict, call: dict) -> float:
    """その呼び出しの実費。**実費が無ければ 0 とはせず、None を返す。**"""
    step = run["usage"]["by_step"].get(call["step"], {})
    # 工程に 1 回しか呼び出しが無ければ、その工程の実費がそのまま該当する。
    if step.get("request_attempts") == 1:
        return step.get("actual_usd", 0.0)
    return 0.0


def _with_shared(a: dict, c: dict, shared: dict | None) -> tuple[float, float]:
    """両方に計画生成を足した実費。"""
    if shared is None:
        return a["actual_usd"], c["actual_usd"]
    generated_by_a = "生成" in (a["run"]["search_plan"]["source"] or "")
    return (
        a["actual_usd"] + (0.0 if generated_by_a else shared["usd"]),
        c["actual_usd"] + (shared["usd"] if generated_by_a else 0.0),
    )


def _rows(a: dict, c: dict, shared: dict | None):
    la, lc = _with_shared(a, c, shared)
    extra_ms = shared["ms"] if shared else 0
    generated_by_a = "生成" in (a["run"]["search_plan"]["source"] or "")
    ta = a["total_ms"] + (0 if generated_by_a else extra_ms)
    tc = c["total_ms"] + (extra_ms if generated_by_a else 0)
    return [
        ("全体時間", f"{ta / 1000:.1f} 秒", f"{tc / 1000:.1f} 秒"),
        ("OrcaRouter 実費", f"${la:.6f}", f"${lc:.6f}"),
        ("実費不明", str(a["unknown_cost"]), str(c["unknown_cost"])),
        ("LLM 実リクエスト", str(a["requests"]), str(c["requests"])),
        ("Jev", "—", f"{a['jev_requests'] or c['jev_requests']} 回 ${c['jev_usd']:.6f}"),
        ("検索", f"{a['search']} 回", f"{c['search']} 回"),
        ("本文取得", f"{a['fetch_ok']}/{a['fetch']}", f"{c['fetch_ok']}/{c['fetch']}"),
        ("候補数", str(a["candidates"]), str(c["candidates"])),
    ]


if __name__ == "__main__":
    sys.exit(main())
