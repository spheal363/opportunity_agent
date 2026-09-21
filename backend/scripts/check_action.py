"""推薦する行動を特定できるか、4 種類で確かめる（#65）。

    .venv/bin/python -m scripts.check_action
    .venv/bin/python -m scripts.check_action --confirm

**4 回は予備確認。品質保証ではない。**

保存済みのページ本文を、**修正後の prompt で組み直して**投げる。
Retry・Fallback なし。生出力・正規化後・最終判定・usage・実費・
request ID を保存する。

## 見るのは「埋まったか」ではない

`recommended_action` が入ったかどうかではなく、**入力にその行動と対象の
根拠があるか**を見る。申込先 URL は入力にある場合だけ使ってよく、
推測で作ってはいけない。

記事に募集先が書かれている場合、**推薦の対象は記事そのものではなく、
その具体的な機会**であること。受付状況は別の判定で、不明なら unknown。

**明確な募集を null にして落とす誤りも見る。**
行動を特定できなかった候補をすべて「記事や一覧」と説明しない。
抽出の失敗や、入力の情報不足のこともある。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path

from ai import availability, evidence
from ai.llm import _extract_json
from ai.orcarouter import LLMRequestError, ModelTier, OrcaRouterClient
from ai.prompts import extraction as prompt
from ai.schemas.extraction import MAX_PAGE_CONTENT_CHARS as LIMIT
from ai.schemas.extraction import ExtractedOpportunity
from config import get_settings
from scripts import _experiment

_experiment.apply_recording_settings()

RUN = Path(__file__).resolve().parent.parent / "experiments" / "run-A-20260921-014407"
TODAY = date(2026, 9, 21)


@dataclass(frozen=True)
class Case:
    kind: str
    url_part: str
    expect_action: bool | None  # None は「入力しだい」
    note: str


CASES = [
    Case(
        "① 他人の投稿作品ページ",
        "cerebralvalley.ai",
        False,
        "本人が応募できるものではない。**行動を特定できないのが正しい**",
    ),
    Case(
        "② 募集先を特定できない記事",
        "hk.finance.yahoo.com/news/%E6%93%9A%E5%82%B3",
        False,
        "中国語圏の企業ニュース。募集先が書かれていない",
    ),
    Case(
        "③ 明確な募集ページ",
        "zenn.dev/hackathons/google-cloud",
        True,
        "**null にしたら誤り。** 応募できる催しの告知",
    ),
    Case(
        "④ 記事だが募集先を特定できる",
        "prtimes.jp/main/html/rd/p/000000081",
        None,
        "プレスリリース。**入力に申込先があれば**行動を特定できるはず",
    ),
]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--report-only", action="store_true", help="保存済みの結果を読み直す")
    args = ap.parse_args()

    if args.report_only:
        _report(json.loads((RUN / "action-check.json").read_text())["results"])
        return 0

    run = json.loads((RUN / "run.json").read_text())
    targets = [(c, _find(run, c.url_part)) for c in CASES]
    missing = [c.kind for c, t in targets if t is None]

    print("=== 実行計画 ===")
    for c, t in targets:
        print(f"  {c.kind:26} {'見つかった' if t else '**保存データに無い**'}")
    print(f"  {len(CASES)} 件 x 1 回 = {len(CASES)} リクエスト")
    print("  Retry / Fallback  **どちらも無効**")
    print("  **4 回は予備確認。品質保証ではない。**")
    print()
    if missing:
        print(f"対象が足りません: {missing}")
        return 1
    if not args.confirm:
        print("実行するには --confirm を付けてください。**まだ API を呼んでいません。**")
        return 0
    if not get_settings().orcarouter_api_key:
        print("ORCAROUTER_API_KEY が未設定です。")
        return 1

    client = OrcaRouterClient()
    try:
        results = [_one(client, c, t) for c, t in targets]
    finally:
        client.close()

    (RUN / "action-check.json").write_text(
        json.dumps(
            {"at": datetime.now(UTC).isoformat(), "results": results}, ensure_ascii=False, indent=2
        )
    )
    _report(results)
    return 0


def _find(run: dict, part: str) -> dict | None:
    for call in run["llm_calls"]:
        if call["step"] != "extraction":
            continue
        body = call["messages"][1]["content"]
        url = next(
            (
                x.replace("取得元 URL:", "").strip()
                for x in body.splitlines()
                if x.startswith("取得元 URL:")
            ),
            "",
        )
        if part in url:
            inner = body.split("<page_content>\n", 1)[1].split("\n</page_content>", 1)[0]
            title = next(
                (
                    x.replace("取得元のページタイトル:", "").strip()
                    for x in inner.splitlines()
                    if x.startswith("取得元のページタイトル:")
                ),
                None,
            )
            return {"url": url, "content": inner.partition("\n\n")[2], "title": title}
    return None


def _one(client: OrcaRouterClient, case: Case, target: dict) -> dict:
    content = target["content"][:LIMIT]
    messages = [
        {"role": "system", "content": prompt.SYSTEM},
        {
            "role": "user",
            "content": prompt.build_user(
                target["url"], content, today=TODAY, source_title=target["title"]
            ),
        },
    ]
    started = time.perf_counter()
    try:
        res = client.chat(
            messages,
            tier=ModelTier.STANDARD,
            json_mode=True,
            max_tokens=8192,
            include_cost=True,
        )
    except LLMRequestError as exc:
        return {"kind": case.kind, "url": target["url"], "error": str(exc)}

    usage = {
        "cost_usd": res.usage.cost_usd,
        "request_id": res.usage.request_id,
        "prompt_tokens": res.usage.prompt_tokens,
        "completion_tokens": res.usage.completion_tokens,
        "reasoning_tokens": res.usage.reasoning_tokens,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
    }
    try:
        parsed = ExtractedOpportunity.model_validate(json.loads(_extract_json(res.content)))
    except Exception as exc:  # noqa: BLE001
        return {
            "kind": case.kind,
            "url": target["url"],
            "raw": res.content,
            **usage,
            "error": f"Schema 不通過: {type(exc).__name__}: {exc}",
        }

    grounded = evidence.ground_deadline_kind(parsed, content)
    status, reason = availability.for_extracted(grounded, now=datetime(2026, 9, 21, 12, tzinfo=UTC))
    action = grounded.recommended_action
    target_text = grounded.action_target
    return {
        "kind": case.kind,
        "expect_action": case.expect_action,
        "note": case.note,
        "url": target["url"],
        **usage,
        "raw": res.content,
        "normalized": grounded.model_dump(mode="json"),
        "availability": str(status),
        "availability_reason": reason,
        # **入力に根拠があるか。** 推測で作っていないかを見る。
        "action_in_source": bool(action) and evidence.quote_is_in_source(action, content),
        "target_in_source": bool(target_text) and evidence.quote_is_in_source(target_text, content),
        "target_is_the_page_itself": bool(target_text) and target_text.strip() == target["url"],
    }


def _report(results: list[dict]) -> None:
    for r in results:
        print(f"========== {r['kind']} ==========")
        print(f"  {r['url'][:76]}")
        print(f"  期待: {r['note']}")
        if "error" in r:
            print(f"  **失敗** {r['error']}\n")
            continue
        n = r["normalized"]
        print(f"  type={n['type']}  title={n['title'][:40]}")
        print(f"  recommended_action = {n['recommended_action']!r}")
        print(f"  action_target      = {str(n['action_target'])[:70]!r}")
        print(f"  受付 {r['availability']}  {r['availability_reason'] or ''}")
        print("  根拠:")
        print(f"    行動の語が入力にある  {r['action_in_source']}")
        print(f"    対象が入力にある      {r['target_in_source']}")
        print(f"    対象がページ自身      {r['target_is_the_page_itself']}")
        print(f"  判定: {_judge(r)}\n")

    ok = [r for r in results if "cost_usd" in r and r["cost_usd"] is not None]
    unknown = [r for r in results if "cost_usd" not in r or r["cost_usd"] is None]
    print("=== 使用量 ===")
    print(
        f"  実費 ${sum(r['cost_usd'] for r in ok):.6f}（{len(ok)} 件）"
        f" / **実費不明 {len(unknown)} 件**"
    )
    print(f"  request ID {len([r for r in results if r.get('request_id')])} 件を保存")


def _judge(r: dict) -> str:
    n = r["normalized"]
    got = bool(n["recommended_action"])
    want = r["expect_action"]
    if want is True and not got:
        return "**不合格。明確な募集を落とした**"
    if want is False and got:
        return "**不合格。応募できないページに行動を付けた**"
    # **対象が None なのは「推測で作った」ではない。** モデルが出さなかっただけ。
    # 推測を疑うのは、値があるのに入力に無いとき。
    target = n["action_target"]
    if got and target and not r["target_in_source"] and not r["target_is_the_page_itself"]:
        return "**不合格。対象の値が入力に無い（推測で作った疑い）**"
    if got and not target:
        note = "（対象は未取得。ページ自身を申込先とみなすしかない）"
        return f"合格{note}" if want is not False else "**不合格**"
    if want is None:
        return f"（入力しだい）行動={'あり' if got else 'なし'}"
    return "合格"


if __name__ == "__main__":
    sys.exit(main())
