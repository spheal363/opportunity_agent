"""保存済みの候補で、**現行の選別と方向枠つきの選別を比べる**（#65）。

    .venv/bin/python -m scripts.compare_prefilter <C の実験ディレクトリ>
    .venv/bin/python -m scripts.compare_prefilter <C の実験ディレクトリ> --confirm

## 見立ては 1 回だけ取る

同じ候補に Jev を 1 度だけ投げ、**同じ見立てで 2 つの並べ方を比べる。**
別々に投げると、並べ方の違いとモデルの揺れが混ざる。

Jev の呼び出しは候補数ぶんだけ（20 件なら 20 回、約 $0.001）。
**LLM の選別呼び出しは増やさない。**

## 分かること / 分からないこと

分かるのは **どの候補が入れ替わるか**まで。
**本文を読んでいないので、品質が良くなったとは言えない。**
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ai import cost
from ai.jev import prefilter as pf
from ai.jev.client import JevClient
from config import get_settings
from scripts import _experiment
from tools.search.base import SearchResult

_experiment.apply_recording_settings()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    directory = Path(args.directory).resolve()
    run = json.loads((directory / "run.json").read_text())
    saved = run["prefilter"]
    candidates = saved["read"] + saved["deferred"]
    limit = len(saved["read"])
    queries = list(dict.fromkeys(c["query"] for c in candidates))
    directions = [queries.index(c["query"]) for c in candidates]

    print("=== 比較の計画 ===")
    print(f"  候補 {len(candidates)} 件 / 読む上限 {limit} 件（**維持**）")
    print(f"  探索方向 {len(queries)} 件")
    print(f"  Jev 呼び出し {len(candidates)} 回（**1 度だけ。同じ見立てで 2 通り並べる**）")
    print("  LLM の選別呼び出しは増やさない。検索・本文取得はやり直さない。")
    print()
    if not args.confirm:
        print("実行するには --confirm を付けてください。**まだ API を呼んでいません。**")
        return 0
    if not get_settings().typesafe_api_key:
        print("TYPESAFE_API_KEY が未設定です。")
        return 1

    results = [
        SearchResult(title=c["title"], url=c["url"], snippet=c["snippet"], content=None)
        for c in candidates
    ]
    goal = _goal(run)

    client = JevClient()
    try:
        with cost.track() as tracker, cost.step("prefilter"):
            verdicts = pf.map_parallel(
                list(enumerate(results)),
                lambda pair: pf._one(
                    client,
                    index=pair[0],
                    result=pair[1],
                    goal_summary=goal[0],
                    interest_connections=goal[1],
                ),
            )
    finally:
        client.close()

    before, slots_before = pf._order(verdicts, limit=limit)
    after, slots_after = pf._order(verdicts, limit=limit, directions=directions)

    payload = {
        "limit": limit,
        "queries": queries,
        "usage": tracker.to_dict(),
        "candidates": [
            {
                **c,
                "direction": directions[i],
                "relevance": verdicts[i].relevance,
                "serendipity": verdicts[i].serendipity,
                "looks_like_article": verdicts[i].looks_like_article,
                "snippet_is_unclear": verdicts[i].snippet_is_unclear,
                "read_before": i in before[:limit],
                "read_after": i in after[:limit],
                "slot_before": slots_before.get(i),
                "slot_after": slots_after.get(i),
                "deferred_reason": None
                if i in after[:limit]
                else ("記事らしい" if verdicts[i].looks_like_article else "上限に入らなかった"),
            }
            for i, c in enumerate(candidates)
        ],
    }
    (directory / "prefilter-comparison.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2)
    )
    _report(payload, before[:limit], after[:limit])
    return 0


def _goal(run: dict) -> tuple[str, list[str]]:
    for call in run["llm_calls"]:
        if call["step"] != "prefilter" and call["step"] != "evaluation":
            continue
        body = call["messages"][1]["content"]
        if "目標: " in body:
            goal = body.split("目標: ", 1)[1].split("\n", 1)[0]
            line = (
                body.split("興味の交差点: ", 1)[1].split("\n", 1)[0]
                if "興味の交差点: " in body
                else ""
            )
            return goal, [x.strip() for x in line.split(",") if x.strip()]
    # 評価が Jev だった run には LLM のプロンプトが無い。profile から組む。
    p = run["profile"]
    return "、".join(p["goals"]), p["interests"]


def _report(payload: dict, before: list[int], after: list[int]) -> None:
    cands = payload["candidates"]
    print("=== 方向ごとの配分 ===")
    print(f"  {'方向':50} {'現行':>8} {'方向枠つき':>10}")
    for d, q in enumerate(payload["queries"]):
        b = sum(1 for c in cands if c["direction"] == d and c["read_before"])
        a = sum(1 for c in cands if c["direction"] == d and c["read_after"])
        mark = "  <-" if b != a else ""
        print(f"  {q[:48]:50} {b:8} {a:10}{mark}")
    print()

    added = [c for c in cands if c["read_after"] and not c["read_before"]]
    dropped = [c for c in cands if c["read_before"] and not c["read_after"]]
    print(f"=== 入れ替わり（{len(added)} 件）===")
    for c in added:
        print(f"  + {c['title'][:44]:46} 方向{c['direction']} 枠={c['slot_after']}")
    for c in dropped:
        print(f"  - {c['title'][:44]:46} 方向{c['direction']} 枠(現行)={c['slot_before']}")
    print()
    usage = payload["usage"]
    jev = sum(u.get("jev", {}).get("usd", 0) for u in usage["by_step"].values())
    n = sum(u.get("jev", {}).get("request_attempts", 0) for u in usage["by_step"].values())
    print(f"=== 費用 ===\n  Jev {n} 回 ${jev:.6f}（公式単価 x 実トークン。請求額ではない）")
    print("\n  **本文を読んでいないので、品質が良くなったとは言えない。**")
    print("  言えるのは、どの候補が読まれるようになったかまで。")


if __name__ == "__main__":
    sys.exit(main())
