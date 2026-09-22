"""希望別 4 リクエストの回答を統合し、出典と照合する（#47）。

**発見工程とは別に時間を測る。**

## 照合の厳しさ

**「ページ内にその語がある」では合格にしない。**
大学名とキャンパス名の混同（実測）は、語がどちらもページにあるのに
**別々の行**だったために起きた。

ここでは、開催日・会場・地域が**本文中で近い位置にあるか**を見る。
離れていれば「同じまとまりに対応していない」として不合格にする。
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

from ai import interstitial  # noqa: E402
from tools import registry  # noqa: E402

RA = "ra.co"
SKIP = ("instagram.com", "facebook.com", "x.com", "twitter.com", "youtube.com")
# 同じまとまりとみなす最大の距離（正規化後の文字数）。
NEAR = 400

CANDS = [
    {
        "wish": "音楽",
        "name": "John Talabot",
        "dates": ["2026-10-03"],
        "venue": "VENT",
        "src": "https://ra.co/events/2515227",
    },
    {
        "wish": "音楽",
        "name": "Carlos Souffront",
        "dates": ["2026-10-10"],
        "venue": "VENT",
        "src": "https://nightlifetokyo.com/ja/tokyo/events/73ef3607-8b2b-4857-bcdb-a7e8627c0688",
    },
    {
        "wish": "音楽",
        "name": "31st Anniversary Special X-tra gaiden",
        "dates": ["2026-11-15"],
        "venue": "Z Maruyama",
        "src": "https://ra.co/events/2537808",
    },
    {
        "wish": "音楽",
        "name": "PICNIC PEOPLE PANIC",
        "dates": ["2026-11-13"],
        "venue": "WOMB",
        "src": "https://soundcheck.club/tokyo/house/2026-11/",
    },
    {
        "wish": "音楽",
        "name": "HOUSE-TEX",
        "dates": ["2026-11-05"],
        "venue": "Bridge",
        "src": "https://soundcheck.club/tokyo/house/2026-11/",
    },
    {
        "wish": "DTM・作曲",
        "name": "音源道場Plus ミックスセミナー初級編",
        "dates": ["2026-10-03"],
        "venue": "島村楽器 立川店",
        "src": "https://www.shimamura.co.jp/update/shops/tachikawa/dtm-recording/72789/",
    },
    {
        "wish": "ハッカソン",
        "name": "PLATEAU Hack Challenge 2026 in Tokyo",
        "dates": ["2026-09-26", "2026-09-27"],
        "venue": "TUNNEL TOKYO",
        "src": "https://prtimes.jp/main/html/rd/p/000000284.000017610.html",
    },
    {
        "wish": "ハッカソン",
        "name": "Tokyo Agent Hackathon",
        "dates": ["2026-10-17"],
        "venue": "（会場名は回答でも不明）",
        "src": "https://japanhackathons.com/events/tokyo-agent-hackathon",
    },
    {
        "wish": "ハッカソン",
        "name": "都知事杯オープンデータ・ハッカソン 2026 Final Stage",
        "dates": ["2026-10-17"],
        "venue": "（会場名は回答でも不明）",
        "src": "https://www.metro.tokyo.lg.jp/information/press/2026/09/2026091813",
    },
    {
        "wish": "ポケモン",
        "name": "レジェンドリサーチ in 日本橋＆八重洲〈10月〉",
        "dates": ["2026-10-01", "2026-10-31"],
        "venue": "日本橋・八重洲",
        "src": "https://t.pia.jp/vi/pia/event/event.do",
    },
]


def norm(t: str) -> str:
    return re.sub(r"\s+", "", unicodedata.normalize("NFKC", t or "")).lower()


def forms(iso: str) -> list[str]:
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
        f"{en[mo - 1]}{d}",
        f"{en[mo - 1]}{d:02d}",
    ]


def positions(body: str, needles: list[str]) -> list[int]:
    out = []
    for n in needles:
        if not n:
            continue
        out += [m.start() for m in re.finditer(re.escape(norm(n)), body)]
    return out


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
    out_dir = Path("../docs/experiments/47-search-model/five-20260922-170649")
    (out_dir / "audit-pages").mkdir(exist_ok=True)
    t0 = time.monotonic()
    searches = fetches = 0
    rows = []
    for c in CANDS:
        r = {
            **c,
            "checked_url": None,
            "date_found": 0,
            "near_ok": None,
            "date_verdict": "",
            "registration": "未確認",
            "eligibility": "本人との照合未実施",
            "note": "",
        }
        body = ""
        if RA not in c["src"]:
            body = fetch(c["src"])
            fetches += 1
            if body:
                r["checked_url"] = c["src"]
        if not body:
            r["note"] = "出典を取得できず、別出典を検索" if RA in c["src"] else "出典を取得できず"
            try:
                res = registry.invoke(
                    "search_web", query=f"{c['name']} {c['venue']} 2026", limit=8
                ).data
                searches += 1
            except Exception:  # noqa: BLE001
                res = []
            for s in res:
                if RA in s.url or any(k in s.url for k in SKIP):
                    continue
                body = fetch(s.url)
                fetches += 1
                if body and len(body) > 400:
                    r["checked_url"] = s.url
                    break
                body = ""
        if not body:
            r["date_verdict"] = "出典取得不能（未確認）"
            rows.append(r)
            continue
        (out_dir / "audit-pages" / (re.sub(r"\W+", "_", c["name"])[:44] + ".txt")).write_text(
            f"URL: {r['checked_url']}\n\n{body}"
        )
        nb = norm(body)
        dpos = {d: positions(nb, forms(d)) for d in c["dates"]}
        r["date_found"] = sum(1 for d, p in dpos.items() if p)
        vpos = positions(nb, [c["venue"]]) if "不明" not in c["venue"] else []
        if r["date_found"] == 0:
            r["date_verdict"] = "未確認（出典に日程が出ない）"
        elif not vpos:
            r["date_verdict"] = (
                "日程のみ確認（会場は出典で照合できず）"
                if r["date_found"] == len(c["dates"])
                else "一部確認（日程の一部のみ）"
            )
        else:
            near = any(abs(a - b) <= NEAR for p in dpos.values() for a in p for b in vpos)
            r["near_ok"] = near
            if r["date_found"] == len(c["dates"]) and near:
                r["date_verdict"] = "日程・会場が同じまとまりで一致"
            elif near:
                r["date_verdict"] = "一部確認（日程の一部のみ）"
            else:
                r["date_verdict"] = "**不合格（日程と会場が離れた位置＝別のまとまり）**"
        rows.append(r)

    secs = round(time.monotonic() - t0, 1)
    (out_dir / "audit.json").write_text(json.dumps(rows, ensure_ascii=False, indent=1))
    for r in rows:
        print(f"[{r['wish']}] {r['name'][:44]}")
        print(
            f"   {r['date_verdict']}  日程 {r['date_found']}/{len(r['dates'])}"
            f"  近接 {r['near_ok']}  {r['note']}"
        )
        print(f"   受付 {r['registration']} / 参加資格 {r['eligibility']}")
        print(f"   照合先 {r['checked_url'] or '（取得できず）'}")
    from collections import Counter

    print("\n判定内訳:", dict(Counter(r["date_verdict"] for r in rows)))
    print(f"照合工程: {secs} 秒 / 検索 {searches} 回 / 取得 {fetches} 回 / LLM 0 回")
    return 0


if __name__ == "__main__":
    sys.exit(main())
