"""Tavily の地域・言語指定を、問題のクエリで比べる（#65）。**LLM は使わない。**

    .venv/bin/python -m scripts.check_locale
    .venv/bin/python -m scripts.check_locale --confirm

## 公式で確認した仕様（docs.tavily.com の /search）

  country            その国の結果を**押し上げる**。`topic` が general のときだけ
  language           その言語の結果を**押し上げる**
  filter_by_language 押し上げではなく**絞り込む**。既定 false

**Serper の `gl` / `hl` と同じ意味ではない。** あちらは Google のロケール
指定で、こちらは既定では順位付けへの加点にとどまる。

## 一律適用はしない

日本へ寄せると、**海外開催のオンライン機会や英語の募集を落とす**恐れが
ある。ここで見るのは「変えたら何がどう変わるか」まで。

## 費用

**「LLM を使わないからほぼ無料」とはしない。** Tavily の検索は 1 回ごとに
使用量が発生する。今回の利用量を記録し、**単価と残量は未確認**とする。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlparse

from config import get_settings
from tools.search.tavily import TavilyProvider

# 実測で無関係な結果が返ったクエリ（A の run から）。
QUERY = "AI Agent スタートアップ 支援 東京 募集"
LIMIT = 5

OUT = Path(__file__).resolve().parent.parent / "experiments" / "tavily-locale.json"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true")
    args = ap.parse_args()

    print("=== 実行計画 ===")
    print(f"  クエリ      {QUERY}")
    print(f"  検索        2 回（既定 / country=japan + language=ja）、各 {LIMIT} 件")
    print("  **他のパラメータは揃える。** 変えるのは地域・言語だけ")
    print("  LLM は呼ばない。**ただし Tavily の使用量は 2 回ぶん発生する**")
    print("  Tavily の単価・残量は**未確認**")
    print()
    if not args.confirm:
        print("実行するには --confirm を付けてください。**まだ API を呼んでいません。**")
        return 0
    if not get_settings().search_api_key:
        print("SEARCH_API_KEY が未設定です。")
        return 1

    provider = TavilyProvider()
    try:
        base = provider.search(QUERY, limit=LIMIT)
        localized = provider.search(QUERY, limit=LIMIT, country="japan", language="ja")
    finally:
        provider.close()

    payload = {
        "at": datetime.now(UTC).isoformat(),
        "query": QUERY,
        "limit": LIMIT,
        "tavily_searches": 2,
        "note": "**単価・残量は未確認。** 使用量だけ記録する",
        "default": [_row(r) for r in base],
        "localized": [_row(r) for r in localized],
    }
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2))
    _report(payload)
    return 0


def _row(r) -> dict:
    return {
        "title": r.title,
        "url": r.url,
        "host": urlparse(r.url).netloc,
        "snippet": (r.snippet or "")[:120],
        "score": r.score,
    }


def _report(payload: dict) -> None:
    for label, key in (
        ("既定（指定なし）", "default"),
        ("country=japan, language=ja", "localized"),
    ):
        print(f"=== {label} ===")
        for r in payload[key]:
            print(f"  {r['host'][:30]:32} {r['title'][:46]}")
        print()

    before = {r["url"] for r in payload["default"]}
    after = {r["url"] for r in payload["localized"]}
    print(
        f"=== 入れ替わり ===\n  共通 {len(before & after)} 件 / 変更後のみ {len(after - before)} 件"
    )
    for r in payload["localized"]:
        if r["url"] not in before:
            print(f"  + {r['title'][:52]}")
    for r in payload["default"]:
        if r["url"] not in after:
            print(f"  - {r['title'][:52]}")
    print()
    print(f"=== 使用量 ===\n  Tavily 検索 {payload['tavily_searches']} 回")
    print("  **単価・残量とも未確認。** 支払い額は出せない。")
    print("\n  **一律適用はしない。** 海外開催のオンライン機会や英語の募集を")
    print("  落とす恐れがあり、それはこの 1 クエリでは分からない。")


if __name__ == "__main__":
    sys.exit(main())
