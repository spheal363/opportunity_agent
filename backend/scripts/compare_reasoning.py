"""同じ入力で、思考量の設定だけを変えて比べる（#65）。

**検索・本文取得はやり直さない。** A の run で保存した入力を再利用する。

    # 計画だけ表示（API は呼ばない）
    .venv/bin/python -m scripts.compare_reasoning <実験ディレクトリ>
    # 実行
    .venv/bin/python -m scripts.compare_reasoning <実験ディレクトリ> --confirm

## 何を確かめるか

**パラメータが受理されたことと、実際に効いたことは別。**
`reasoning_effort` を送って HTTP 200 が返っても、
`usage.completion_tokens_details.reasoning_tokens` が減らなければ
反映されていない。**必ずトークン数で確かめる。**

## max_tokens は下げない

枠を削ると JSON が途中で切れ、Retry が増えて逆に高くつく（実測でそうなった）。
変えるのは `reasoning_effort` だけにする。

## 品質は現行モデルとの一致で測らない

現行が正解ではない。**原文（保存されたページ本文）と並べて出す。**
日時・締切・場所・費用と、null の扱いを人が確かめられる形にする。

キーと認証情報は保存も表示もしない。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

from ai.llm import _extract_json
from ai.orcarouter import LLMRequestError, ModelTier, OrcaRouterClient
from ai.schemas.extraction import ExtractedOpportunity
from config import get_settings

# 現行設定（`reasoning_effort` を送らない）を表す印。
CURRENT = "current"

# 比べる設定。**minimal が Gemini 2.5 Flash で効くかは未確認**なので、
# low も一緒に試す。公式は low / medium / high を共通値とし、
# minimal / max は「一部のモデル」としている。
DEFAULT_EFFORTS = [CURRENT, "low", "minimal"]

# 抽出の 1 回あたりの実測（A の run）。見積もりに使う。
_MEASURED_JPY_PER_EXTRACTION_CALL = 9.90 / 20
_MAX_ATTEMPTS = 3  # ai.llm.DEFAULT_MAX_ATTEMPTS と同じ

# 品質で見る欄。**null の扱いも見る。**
FIELDS = ("title", "type", "start_at", "end_at", "deadline", "location", "cost", "eligibility")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("directory")
    ap.add_argument("--step", default="extraction")
    ap.add_argument("--limit", type=int, default=8)
    ap.add_argument(
        "--index",
        default="",
        help="保存呼び出しの番号をカンマ区切りで指定（--limit より優先）",
    )
    ap.add_argument("--efforts", default=",".join(DEFAULT_EFFORTS))
    ap.add_argument(
        "--max-attempts",
        type=int,
        default=_MAX_ATTEMPTS,
        help="1 件あたりの試行回数。予備実験では 1（自動 Retry なし）",
    )
    ap.add_argument("--confirm", action="store_true", help="実 API を呼ぶ")
    args = ap.parse_args()

    directory = Path(args.directory).resolve()
    run = json.loads((directory / "run.json").read_text())
    efforts = [e.strip() for e in args.efforts.split(",") if e.strip()]

    all_calls = [c for c in run["llm_calls"] if c["step"] == args.step]
    if args.index:
        wanted = [int(x) for x in args.index.split(",") if x.strip()]
        calls = [all_calls[i] for i in wanted]
    else:
        calls = all_calls[: args.limit]
    if not calls:
        print(f"{args.step} の保存呼び出しがありません。")
        return 1

    _plan(calls, efforts, args.step, args.max_attempts)
    if not args.confirm:
        print("実行するには --confirm を付けてください。**まだ API を呼んでいません。**")
        return 0

    settings = get_settings()
    if not settings.orcarouter_api_key:
        print("ORCAROUTER_API_KEY が未設定です。")
        return 1

    client = OrcaRouterClient()
    try:
        results = _run_all(client, calls, efforts, max_attempts=args.max_attempts)
    finally:
        client.close()

    _save(directory, args.step, efforts, results)
    _report(calls, efforts, results)
    return 0


def _plan(calls: list[dict], efforts: list[str], step: str, max_attempts: int) -> None:
    n = len(calls) * len(efforts)
    jpy = n * _MEASURED_JPY_PER_EXTRACTION_CALL
    per = _MEASURED_JPY_PER_EXTRACTION_CALL
    print("=== 実行計画（**予算見積もり。実測ではない**）===")
    print(f"  工程          {step}")
    print(f"  対象          {len(calls)} 件 x {len(efforts)} 設定 = {n} 呼び出し")
    print(f"  試行上限      1 件あたり {max_attempts} 回 -> 最大 {n * max_attempts} リクエスト")
    if max_attempts == 1:
        print("                **自動 Retry なし。失敗も結果として記録する。**")
    print(f"  費用見積もり  約 ¥{jpy:.0f}（A の実測 ¥{per:.2f}/回 x {n}）")
    print("  **これは平均単価からの参考額で、厳密な最大費用ではない。**")
    print("  出力長は入力ごとに変わる。上位 tier へ落ちれば単価が 50 倍になる")
    print("  （POWERFUL = claude-opus-4.7、¥2,250/¥11,250 per 1M）。")
    print("  この予備実験では **Fallback を使わない**（tier を固定して直接呼ぶ）。")
    print("  **思考量を下げた側はこれより安くなるはず。下がらなければ効いていない。**")
    print("  max_tokens は変えない。検索・本文取得はやり直さない。")
    print()


def _run_all(
    client: OrcaRouterClient,
    calls: list[dict],
    efforts: list[str],
    *,
    max_attempts: int = _MAX_ATTEMPTS,
) -> list[dict]:
    """**上位 tier へは落とさない。** tier を固定して直接呼ぶ。

    未対応パラメータのエラーが出たら、**別の設定で自動的にやり直さず止める。**
    「この設定では駄目だった」ことを、別の設定の結果で覆い隠さないため。
    """
    out: list[dict] = []
    for index, call in enumerate(calls, 1):
        title = _title_of(call)
        print(f"  [{index}/{len(calls)}] {title[:44]}")
        for effort in efforts:
            out.append(_one(client, call, effort, index, max_attempts=max_attempts))
            r = out[-1]
            if "error" in r:
                print(f"      {effort:9} **失敗** {r['error']}")
                if r.get("fatal"):
                    print("      **停止する。** 別の設定で自動的にやり直さない。")
                    return out
            else:
                print(
                    f"      {effort:9} reasoning {r['reasoning_tokens']:5}  "
                    f"回答 {r['answer_tokens']:4}  {r['elapsed_ms']:6} ms  "
                    f"実費 {_usd(r['cost_usd'])}  試行 {r['attempts']}"
                )
    return out


def _one(
    client: OrcaRouterClient,
    call: dict,
    effort: str,
    index: int,
    *,
    max_attempts: int = _MAX_ATTEMPTS,
) -> dict:
    """1 件 1 設定。**Retry 込みで測る。**

    `max_attempts=1` なら自動 Retry なし。失敗も結果として残す。
    """
    messages = call["messages"]
    max_tokens = call["max_tokens"]
    attempts = 0
    started = time.perf_counter()
    last: Exception | None = None
    fatal = False

    while attempts < max_attempts:
        attempts += 1
        try:
            res = client.chat(
                messages,
                tier=ModelTier.STANDARD,
                json_mode=True,
                max_tokens=max_tokens,
                reasoning_effort=None if effort == CURRENT else effort,
                # **実費を取る。** 見積もりと別の欄に置く。
                include_cost=True,
            )
        except LLMRequestError as exc:
            last = exc
            # **未対応パラメータは 400 で返る想定。** 再試行しても同じなので、
            # 実験そのものを止める材料として上へ伝える。
            fatal = exc.status_code in (400, 404, 422)
            if not exc.retryable:
                break
            continue

        u = res.usage
        return {
            "index": index,
            "effort": effort,
            "attempts": attempts,
            "elapsed_ms": int((time.perf_counter() - started) * 1000),
            "model": u.model,
            "prompt_tokens": u.prompt_tokens,
            "reasoning_tokens": u.reasoning_tokens,
            "answer_tokens": u.completion_tokens - u.reasoning_tokens,
            "completion_tokens": u.completion_tokens,
            "cost_usd": u.cost_usd,
            "request_id": u.request_id,
            "parsed": _parse(res.content),
            "raw": res.content,
        }

    return {
        "index": index,
        "effort": effort,
        "attempts": attempts,
        "elapsed_ms": int((time.perf_counter() - started) * 1000),
        "error": str(last),
        "status": getattr(last, "status_code", None),
        "fatal": fatal,
    }


def _parse(content: str) -> dict | None:
    """抽出結果を Schema へ通す。**通らなければ通らないと持つ。**"""
    try:
        return ExtractedOpportunity.model_validate(json.loads(_extract_json(content))).model_dump(
            mode="json"
        )
    except Exception as exc:  # noqa: BLE001 - 失敗の種類ごとに分けない
        return {"__invalid__": f"{type(exc).__name__}: {exc}"}


def _title_of(call: dict) -> str:
    content = call["messages"][1]["content"]
    for line in content.splitlines():
        if line.startswith("取得元 URL:"):
            return line.replace("取得元 URL:", "").strip()
    return "(不明)"


def _usd(value: float | None) -> str:
    return "**未取得**" if value is None else f"${value:.6f}"


def _save(directory: Path, step: str, efforts: list[str], results: list[dict]) -> None:
    path = directory / f"reasoning-comparison-{step}.json"
    path.write_text(
        json.dumps(
            {
                "at": datetime.now(UTC).isoformat(),
                "step": step,
                "efforts": efforts,
                "note": "**max_tokens は変えていない。** 変えたのは reasoning_effort だけ",
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    print(f"\n保存しました: {path}\n")


def _report(calls: list[dict], efforts: list[str], results: list[dict]) -> None:
    by = {(r["index"], r["effort"]): r for r in results}

    print("=== ① 思考量は実際に減ったか（**受理されただけでは足りない**）===")
    head = f"  {'設定':10} {'reasoning計':>12} {'回答計':>8}"
    print(f"{head} {'時間計 s':>10} {'実費計':>12} {'試行':>5}")
    totals = {}
    for e in efforts:
        rows = [by[(i + 1, e)] for i in range(len(calls)) if (i + 1, e) in by]
        ok = [r for r in rows if "error" not in r]
        rt = sum(r["reasoning_tokens"] for r in ok)
        at = sum(r["answer_tokens"] for r in ok)
        ms = sum(r["elapsed_ms"] for r in rows)
        usd = sum(r["cost_usd"] or 0 for r in ok)
        missing = sum(1 for r in ok if r["cost_usd"] is None)
        att = sum(r["attempts"] for r in rows)
        totals[e] = (rt, at, ms, usd, att, len(ok))
        note = (
            f"  （**実費取得不可** {missing} 件。確定額を引くには追加照会 {missing} 回）"
            if missing
            else ""
        )
        print(f"  {e:10} {rt:12} {at:8} {ms / 1000:10.1f} ${usd:11.6f} {att:5}{note}")
    base = totals.get(CURRENT)
    if base:
        print()
        for e in efforts:
            if e == CURRENT:
                continue
            rt, at, ms, usd, att, n = totals[e]
            if rt == base[0]:
                print(f"  {e:10} **reasoning が変わっていない。効いていない可能性が高い。**")
            else:
                print(
                    f"  {e:10} reasoning {(rt - base[0]) / max(base[0], 1) * 100:+5.0f}%  "
                    f"時間 {(ms - base[2]) / max(base[2], 1) * 100:+5.0f}%  "
                    f"実費 {(usd - base[3]) / max(base[3], 1e-9) * 100:+5.0f}%"
                )
    print()

    print("=== ② 抽出の中身がどう変わったか（**一致は正解ではない**）===")
    for i, call in enumerate(calls, 1):
        cur = by.get((i, CURRENT))
        if cur is None or "parsed" not in cur:
            continue
        print(f"  [{i}] {_title_of(call)[:60]}")
        for e in efforts:
            if e == CURRENT:
                continue
            other = by.get((i, e))
            if other is None or "parsed" not in other:
                print(f"      {e:9} **結果なし**")
                continue
            diffs = _diff(cur["parsed"], other["parsed"])
            if not diffs:
                print(f"      {e:9} 差分なし")
            for f, a, b in diffs:
                kind = (
                    "**null になった**"
                    if b is None
                    else "**null から埋まった**"
                    if a is None
                    else "変化"
                )
                print(f"      {e:9} {f:11} {kind}  現行={a!r} -> {e}={b!r}")
        print()

    print("=== ③ null の扱い ===")
    for e in efforts:
        rows = [by[(i + 1, e)] for i in range(len(calls)) if (i + 1, e) in by]
        ok = [r for r in rows if "parsed" in r and "__invalid__" not in (r["parsed"] or {})]
        counts = {f: sum(1 for r in ok if (r["parsed"] or {}).get(f) is None) for f in FIELDS}
        invalid = sum(1 for r in rows if "__invalid__" in (r.get("parsed") or {}))
        print(f"  {e:10} null の件数 {counts}  Schema 不通過 {invalid}")


def _diff(a: dict, b: dict) -> list[tuple[str, object, object]]:
    return [(f, a.get(f), b.get(f)) for f in FIELDS if a.get(f) != b.get(f)]


if __name__ == "__main__":
    sys.exit(main())
