"""内蔵検索の出力を、別出典で照合する（#47）。**発見工程とは分けて計測する。**

**モデルの自己申告を正しいと扱わない。**
RA（ja.ra.co / ra.co）は本文を取得できないので、イベント名と会場で
別出典（会場公式・チケット販売元）を探して確かめる。

**取得できなかったものは「未確認」。誤りと断定しない。**
"""

from __future__ import annotations

import json
import re
import sys
import time
import unicodedata
from pathlib import Path

from scripts._experiment import apply_recording_settings

apply_recording_settings()

from ai import cost, interstitial  # noqa: E402
from tools import registry  # noqa: E402

RA_HOSTS = ("ra.co",)
SKIP = ("instagram.com", "facebook.com", "x.com", "twitter.com", "youtube.com")


def norm(t: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", t or "")).lower()


def date_forms(iso: str) -> list[str]:
    m = re.match(r"(\d{4})-(\d{2})-(\d{2})", iso or "")
    if not m:
        return []
    y, mo, d = int(m[1]), int(m[2]), int(m[3])
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
    ]


def fetch(url: str) -> str:
    try:
        pages = registry.invoke("read_page", url=url).data["pages"]
    except Exception:  # noqa: BLE001
        return ""
    if not pages:
        return ""
    p = pages[0]
    if interstitial.looks_like_interstitial(title=p.title, content=p.content):
        return ""
    return p.content or ""


def main() -> int:
    base = Path("../docs/experiments/47-orca-websearch-run")
    cands = json.loads((base / "candidates.json").read_text())
    started = time.monotonic()
    searches = fetches = 0
    rows = []
    pages_dir = base / "audit-pages"
    pages_dir.mkdir(exist_ok=True)

    with cost.track() as tracker:
        for c in cands:
            name, url = c["name"], c.get("source_url", "")
            venue = c.get("venue") or c.get("region") or ""
            row = {
                "wish": c["_wish"],
                "name": name,
                "dates": c.get("dates") or [],
                "venue": venue,
                "claimed_url": url,
                "checked_url": None,
                "date_hit": 0,
                "venue_hit": False,
                "verdict": "未確認",
                "why": "",
            }
            body = ""
            if not any(h in url for h in RA_HOSTS):
                body = fetch(url)
                fetches += 1
                if body:
                    row["checked_url"] = url
            if not body:
                # **RA か取得不可。名前と会場で別出典を探す。**
                q = f"{name} {venue} 2026"
                try:
                    res = registry.invoke("search_web", query=q, limit=8).data
                    searches += 1
                except Exception:  # noqa: BLE001
                    res = []
                for r in res:
                    if any(h in r.url for h in RA_HOSTS + SKIP):
                        continue
                    body = fetch(r.url)
                    fetches += 1
                    if body and len(body) > 400:
                        row["checked_url"] = r.url
                        break
                    body = ""
            if not body:
                row["why"] = "別出典も取得できず"
                rows.append(row)
                continue
            (pages_dir / (re.sub(r"\W+", "_", name)[:50] + ".txt")).write_text(
                f"URL: {row['checked_url']}\n\n{body}"
            )
            nb = norm(body)
            row["date_hit"] = sum(
                1 for d in row["dates"] if any(norm(f) in nb for f in date_forms(d))
            )
            row["venue_hit"] = bool(venue) and norm(venue)[:5] in nb
            tokyo = ("東京" in body) or ("tokyo" in body.lower())
            if row["dates"] and row["date_hit"] == len(row["dates"]) and tokyo:
                row["verdict"] = "確認済み"
            elif row["date_hit"] > 0:
                row["verdict"] = "一部確認"
                row["why"] = f"{row['date_hit']}/{len(row['dates'])} の日程のみ一致"
            else:
                row["why"] = "別出典に日程を確認できず"
            rows.append(row)

    secs = round(time.monotonic() - started, 1)
    (base / "audit.json").write_text(json.dumps(rows, ensure_ascii=False, indent=2))
    for r in rows:
        print(f"[{r['wish']}] {r['name'][:42]}")
        print(
            f"   {r['verdict']}  日程 {r['date_hit']}/{len(r['dates'])} / 会場一致 {r['venue_hit']}"
            f"  {r['why']}"
        )
        print(f"   照合先 {r['checked_url'] or '（取得できず）'}")
    ok = [r for r in rows if r["verdict"] == "確認済み"]
    print("\n" + "=" * 64)
    print(f"モデルが返した候補 {len(rows)} 件 / **日程・東京開催を確認できた {len(ok)} 件**")
    from collections import Counter

    print("  確認済みの希望別:", dict(Counter(r["wish"] for r in ok)))
    print("  内訳:", dict(Counter(r["verdict"] for r in rows)))
    print(
        f"照合工程: {secs} 秒 / 検索 {searches} 回 / ページ取得 {fetches} 回 "
        f"/ LLM 呼び出し 0 回（実費 $0）/ request id {len(tracker.request_ids)} 件"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
