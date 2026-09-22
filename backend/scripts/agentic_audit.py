"""試作 v2 の出力を、**保存した取得本文と照合**する（#47）。

**モデルの自己申告をそのまま正しいと扱わない。**
`record_check` が書いた引用・日付・会場が、実際に取得したページの本文に
あるかどうかだけを見る。無ければ「出典で確認できない」と記録する。

取得本文は run ディレクトリの `pages/` にある（全文）。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import unicodedata
from pathlib import Path


def norm(t: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", t or "")).lower()


def load_pages(run_dir: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted((run_dir / "pages").glob("*.txt")):
        text = p.read_text()
        first, _, body = text.partition("\n\n")
        url = first.replace("URL:", "").strip()
        out[url] = norm(body)
    return out


def date_forms(iso: str) -> list[str]:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return []
    y, mo, d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    # **英語表記も見る。** 和文だけで照合すると、`Oct 24(Sat)` と書かれた
    # ページを「本文に無い」と誤判定する（実測）。
    en = ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"]
    return [
        f"{mo}/{d}",
        f"{mo}月{d}日",
        f"{y}.{mo}.{d}",
        f"{y}/{mo}/{d}",
        f"{y}年{mo}月{d}日",
        f"{mo:02d}/{d:02d}",
        f"{y}{mo:02d}{d:02d}",
        f"{en[mo - 1]}{d}",
        f"{en[mo - 1]}{d:02d}",
        f"{d}{en[mo - 1]}",
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("run_dir")
    args = ap.parse_args()
    run_dir = Path(args.run_dir)
    result = json.loads((run_dir / "result.json").read_text())
    pages = load_pages(run_dir)
    print(f"取得済みページ {len(pages)} 件（全文保存）\n")

    rows = []
    for e in result["entries"]:
        chk = e.get("check_result") or {}
        ev_url = (chk.get("evidence_url") or e.get("source_url") or "").strip()
        body = pages.get(ev_url) or pages.get(ev_url.rstrip("/")) or ""
        quote = chk.get("evidence_quote") or ""
        # 引用は表のセルをまたぐと連結される。**短い断片で見る。**
        frags = [f for f in re.split(r"[\s、。／/|]+", quote) if len(f) >= 4][:8]
        hit = sum(1 for f in frags if norm(f) in body)
        dates = chk.get("held_on") or e.get("dates") or []
        date_ok = [d for d in dates if any(norm(f) in body for f in date_forms(d))]
        venue = chk.get("venue") or e.get("venue") or ""
        venue_ok = bool(venue) and norm(venue)[:6] in body
        rows.append(
            {
                "wish": e["wish"],
                "name": e["name"],
                "dates": dates,
                "page_saved": bool(body),
                "quote_hit": f"{hit}/{len(frags)}" if frags else "引用なし",
                "date_in_source": f"{len(date_ok)}/{len(dates)}" if dates else "日程なし",
                "venue_in_source": venue_ok,
                "onsite": chk.get("onsite_tokyo"),
                "confident": chk.get("confident"),
                "registration": chk.get("registration"),
                "eligibility": chk.get("eligibility"),
                "evidence_url": ev_url,
                "found_via": e.get("found_via", ""),
            }
        )

    for r in rows:
        mark = (
            "出典と一致"
            if (
                r["page_saved"]
                and r["date_in_source"].startswith(str(len(r["dates"])))
                and r["dates"]
            )
            else "**要確認**"
        )
        print(f"[{r['wish']}] {r['name'][:44]}")
        print(
            f"   日程 {r['dates']} 本文に {r['date_in_source']} / 会場一致 {r['venue_in_source']}"
            f" / 引用一致 {r['quote_hit']} -> {mark}"
        )
        print(
            f"   東京現地 {r['onsite']} / 確度 {r['confident']} / 受付 {r['registration']}"
            f" / 資格 {r['eligibility']}"
        )
        print(
            f"   出典 {r['evidence_url'][:80]} （保存 {'あり' if r['page_saved'] else '**なし**'}）"
        )
        print(f"   到達経路 {r['found_via'][:96]}")
        print()

    ok = [
        r
        for r in rows
        if r["page_saved"]
        and r["dates"]
        and r["date_in_source"] == f"{len(r['dates'])}/{len(r['dates'])}"
        and r["onsite"] == "はい"
    ]
    print("=" * 66)
    print(
        f"候補 {len(rows)} 件のうち、**日程が出典本文にあり、東京現地と答えたもの: {len(ok)} 件**"
    )
    by = {}
    for r in ok:
        by[r["wish"]] = by.get(r["wish"], 0) + 1
    print("  希望別:", by or "なし")
    reg = sum(1 for r in ok if (r["registration"] or "不明") != "不明")
    eli = sum(1 for r in ok if (r["eligibility"] or "不明") != "不明")
    print(f"  うち受付を確認 {reg} 件 / 参加資格を確認 {eli} 件")
    (run_dir / "audit.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
