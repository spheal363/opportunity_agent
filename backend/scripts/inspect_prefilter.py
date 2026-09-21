"""C の粗選別を、**保存データだけ**から点検する。API は呼ばない。

    .venv/bin/python -m scripts.inspect_prefilter <C の実験ディレクトリ>

**復元できないものは推測しない。** この run では見立て（Jev の点数と
枠の割り当て）を記録していなかったので、そこは「未記録」と書く。

復元できるのは、読んだ／読まなかった候補と、それぞれの検索方向・抜粋・
本文の有無、そして重複と取得失敗。
"""

from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path
from urllib.parse import urlparse


def main() -> int:
    directory = Path(sys.argv[1]).resolve()
    run = json.loads((directory / "run.json").read_text())
    pf = run.get("prefilter")
    if not pf:
        print("粗選別の記録がありません。")
        return 1

    read, deferred = pf["read"], pf["deferred"]
    print(f"=== 候補 {pf['total']} 件 -> 読んだ {len(read)} / 保留 {len(deferred)} ===\n")

    print("=== 検索方向ごとの配分 ===")
    slots = _slots(pf)
    if slots:
        print("  （方向枠つきの選別。枠の割り当ても記録されている）")
    else:
        print("  **この run は方向枠の記録が無い。** 割り当ては推測しない。")
    queries = [c["query"] for c in read + deferred]
    for q in dict.fromkeys(queries):
        r = sum(1 for c in read if c["query"] == q)
        d = sum(1 for c in deferred if c["query"] == q)
        print(f"  読 {r} / 保 {d}   {q}")
    print()

    print("=== 同じサイトからの重複 ===")
    hosts = Counter(urlparse(c["url"]).netloc for c in read + deferred)
    dup = {h: n for h, n in hosts.items() if n > 1}
    print(f"  {dup or 'なし'}")
    titles = Counter(c["title"][:24] for c in read + deferred)
    similar = {k: v for k, v in titles.items() if v > 1}
    print(f"  似たタイトル: {similar or 'なし'}")
    print()

    print("=== 本文の有無（選別時点）===")
    with_content = sum(1 for c in read + deferred if c["has_content"])
    print(f"  抜粋に本文があった候補 {with_content} / {pf['total']}")
    print("  （Serper は本文を返さないので、選別は**タイトルと抜粋だけ**で行われた）")
    print()

    print("=== 本文取得の失敗 ===")
    fetched = _fetched(run)
    failed = [u for u in fetched["failed"]]
    print(f"  試行 {len(fetched['requested'])} / 失敗 {len(failed)}")
    for u in failed:
        hit = next((c for c in read if c["url"] == u), None)
        print(f"    {u[:70]}")
        print(f"      {'読む候補に選ばれていた' if hit else '選ばれていない'}")
    print()

    print("=== 見立ての中身 ===")
    order = pf.get("order")
    if order:
        print(f"  記録あり: {order}")
    else:
        print("  **未記録。** この run では Jev の点数と枠の割り当てを保存していない。")
        print("  復元できるのは順序までで、**なぜその順序になったかは言えない。**")
        print("  コード上の並べ方（ai/jev/prefilter.py の _order）は次のとおり:")
        print("    1. 意外性の上位 2 件を先に取る")
        print("    2. 抜粋だけでは判断できない候補を 1 件取る")
        print("    3. 残りを関連性順")
        print("    4. 記事らしいものは最後")
        print("  **どの候補がどの枠で選ばれたかは、この run からは分からない。**")
    return 0


def _slots(pf: dict) -> dict:
    order = pf.get("order") or []
    return order[0].get("slots", {}) if order else {}


def _fetched(run: dict) -> dict:
    requested: list[str] = []
    failed: list[str] = []
    for t in run["tool_calls"]:
        if t["tool"] != "read_page":
            continue
        # **1 件のときは文字列で渡る。** そのまま extend すると 1 文字ずつ数える。
        url = t["args"]["url"]
        requested.extend([url] if isinstance(url, str) else url)
        failed.extend(t["result"].get("failed", []))
    return {"requested": requested, "failed": failed}


if __name__ == "__main__":
    sys.exit(main())
