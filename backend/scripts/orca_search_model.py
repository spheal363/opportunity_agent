"""検索専用モデル（`openai/gpt-5-search-api` + Chat Completions）の最小経路（#47）。

**新しい探索ロジックを足さない。** 目的は「完成した回答を正常に受け取り、
費用と根拠を記録する」こと。

## この経路を選ぶ理由

- Responses API は `usage.cost_usd` を返さない（仕様）。この経路は**応答に直接乗る**
- 検索専用モデルは指定なしでも検索する（実測済み）

## 記録するもの

HTTP だけで成否を判断しない。**`finish_reason` / 本文 / 引用 / usage /
request ID / 生レスポンス**を必ず保存する。

**切断・エラー・本文なしを「候補 0 件」と扱わない。** 別の状態として記録する。

## 形式

この段階では JSON を必須にしない。**検索と長い JSON 生成を同時に要求すると、
回答が切れたときに成否が分からなくなる**（Responses API で実際に起きた）。
構造化は別工程で行い、**そこで新しい事実を足さない。**
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

from scripts._experiment import apply_recording_settings

apply_recording_settings()

import httpx  # noqa: E402

from config import get_settings  # noqa: E402

WISHES = {
    "音楽": "ハウスやテクノなど四つ打ちの音楽を楽しめるイベントに行きたい",
    "DTM・作曲": "初めての曲作りにつながるDTM・作曲のワークショップに出たい",
    "ハッカソン": "エンジニアとしてプロダクトを作れるハッカソンに参加したい",
    "ポケモン": "ポケモンのイベントにも参加したい",
}

RULES = (
    "・検索で実在を確認したページの URL だけを出す。URL を作らない。\n"
    "・確認できない項目は「不明」と書く。埋めない。\n"
    "・一覧ページではなく、個別の催しを挙げる。\n"
    "・同じ企画の別日程はまとめて 1 件にする。\n"
    "・与えられた希望以外の条件を足さない。職業や経歴を想定しない。\n"
)


def small_prompt(wish_text: str, window: str) -> str:
    return (
        f"【希望】{wish_text}\n"
        f"【地域】東京都内で現地参加できるもの。オンラインのみは対象外。\n"
        f"【期間】{window}\n\n"
        f"この希望に合う催しを 1〜2 件挙げてください。\n"
        f"各件について イベント名 / 開催日 / 会場 / 情報源URL を書いてください。\n"
        f"表でも箇条書きでも構いません。JSON にしなくてよい。\n\n{RULES}"
    )


FIVE_RULES = (
    "・**学校・教室・一覧サイトそのものではなく、具体的な開催回**を挙げる。\n"
    "・**不明な日付を作らない。** 日付が確認できないものは挙げない。\n"
    "・**東京都外・オンラインのみは含めない。**\n"
    "・各件に情報源URLを付ける。\n"
    "・5 件に届かない場合は、**見つかったものと不足の理由**を書く。\n"
    "  5 件は必達ノルマではない。**水増しは禁止。**\n"
    "・**「さらに調べますか？」と聞き返して止まらない。**\n"
    "  今回の依頼の範囲で調べ切って、結果を返す。\n"
)


def five_prompt(wish_text: str, window: str) -> str:
    return (
        f"【希望】{wish_text}\n"
        f"【地域】東京都内で現地参加できるもの。オンラインのみは対象外。\n"
        f"【期間】{window}\n\n"
        f"この希望に合う、**日程のある具体的な企画**を目安 5 件挙げてください。\n"
        f"各件について イベント名 / 開催日 / 東京都内の会場 / 1 行の説明 / 情報源URL。\n"
        f"表でも箇条書きでも構いません。JSON にしなくてよい。\n\n{RULES}{FIVE_RULES}"
    )


def wide_prompt(window: str) -> str:
    lines = "\n".join(f"・{v}" for v in WISHES.values())
    return (
        f"【希望】\n{lines}\n"
        f"【地域】東京都内で現地参加できるもの。オンラインのみは対象外。\n"
        f"【期間】{window}\n\n"
        f"4 つの希望を広くカバーするように、具体的な催しを合計 20 件程度挙げてください。\n"
        f"各件は イベント名 / 開催日 / 東京都内の会場 / 1 行の説明 / 情報源URL だけで"
        f"構いません。**長い推薦文は不要です。**\n"
        f"どの希望に当たるかを各件に添えてください。\n\n{RULES}"
    )


def call(client: httpx.Client, model: str, prompt: str, max_tokens: int) -> dict:
    s = get_settings()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "web_search_options": {},
    }
    t = time.monotonic()
    r = client.post(
        f"{s.orcarouter_base_url}/chat/completions",
        headers={
            "Authorization": f"Bearer {s.orcarouter_api_key}",
            "Content-Type": "application/json",
            "X-OrcaRouter-Include-Cost": "true",
        },
        json=payload,
    )
    out: dict = {
        "sent": payload,
        "http": r.status_code,
        "request_id": r.headers.get("X-Orca-Request-Id"),
        "seconds": round(time.monotonic() - t, 1),
    }
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        out["raw_text"] = r.text[:2000]
        return out
    out["body"] = body
    if r.status_code != 200:
        return out
    choice = (body.get("choices") or [{}])[0]
    msg = choice.get("message") or {}
    out["finish_reason"] = choice.get("finish_reason")
    out["content"] = msg.get("content")
    out["content_len"] = len(msg.get("content") or "")
    out["annotations"] = msg.get("annotations") or []
    out["usage"] = body.get("usage") or {}
    out["cost_usd_inline"] = (body.get("usage") or {}).get("cost_usd")
    return out


def settled(rid: str) -> float | None:
    """**権威ある決済記録。** 取れなければ None（不明）。"""
    if not rid:
        return None
    s = get_settings()
    for _ in range(3):
        try:
            r = httpx.get(
                "https://api.orcarouter.ai/v1/generation",
                params={"id": rid},
                headers={"Authorization": f"Bearer {s.orcarouter_api_key}"},
                timeout=60,
                follow_redirects=True,
            )
        except Exception:  # noqa: BLE001
            return None
        if r.status_code == 200:
            return (r.json().get("data") or {}).get("total_cost")
        time.sleep(3)
    return None


def verdict(res: dict) -> str:
    """**HTTP だけで成否を決めない。**"""
    if res["http"] != 200:
        return f"HTTPエラー {res['http']}"
    fr = res.get("finish_reason")
    if not (res.get("content") or "").strip():
        return f"本文なし（finish_reason={fr}）"
    if fr == "length":
        return "本文が上限で切れた（finish_reason=length）"
    if fr != "stop":
        return f"正常終了ではない（finish_reason={fr}）"
    return "正常完了"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--mode", choices=["small", "wide", "five"], default="small")
    ap.add_argument("--model", default="openai/gpt-5-search-api")
    ap.add_argument("--max-tokens", type=int, default=2000)
    ap.add_argument("--out", default="../docs/experiments/47-search-model")
    args = ap.parse_args()

    from ai import window as w

    win = w.for_now()
    window = f"{win.start:%Y年%m月%d日}〜{win.end:%Y年%m月%d日}"
    print(f"=== {args.mode} / {args.model} / 期間 {window} ===")
    if not args.confirm:
        print("--confirm を付けると実行します")
        return 0

    stamp = time.strftime("%Y%m%d-%H%M%S")
    run_dir = Path(args.out) / f"{args.mode}-{stamp}"
    run_dir.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    calls = []
    with httpx.Client(timeout=600) as client:
        if args.mode == "small":
            jobs = [(k, small_prompt(v, window)) for k, v in WISHES.items()]
        elif args.mode == "five":
            jobs = [(k, five_prompt(v, window)) for k, v in WISHES.items()]
        else:
            jobs = [("4希望まとめて", wide_prompt(window))]

        if args.mode == "five":
            # **並列実行。** 時間は合計ではなく、全体の開始から終了まで測る。
            from concurrent.futures import ThreadPoolExecutor

            with ThreadPoolExecutor(max_workers=len(jobs)) as ex:
                futs = [
                    ex.submit(call, client, args.model, prompt, args.max_tokens)
                    for _, prompt in jobs
                ]
                done = [f.result() for f in futs]
            results = list(zip([j[0] for j in jobs], done, strict=True))
        else:
            results = [
                (label, call(client, args.model, prompt, args.max_tokens)) for label, prompt in jobs
            ]

        for label, res in results:
            res["label"] = label
            res["verdict"] = verdict(res)
            res["cost_usd_settled"] = settled(res.get("request_id") or "")
            calls.append(res)
            (run_dir / f"{label.replace('/', '_')}.json").write_text(
                json.dumps(res, ensure_ascii=False, indent=1)
            )
            inline = res.get("cost_usd_inline")
            st = res.get("cost_usd_settled")
            print(
                f"\n--- {label} --- {res['verdict']}\n"
                f"  HTTP {res['http']} / finish_reason {res.get('finish_reason')} "
                f"/ 本文 {res.get('content_len', 0)} 字 "
                f"/ 引用 {len(res.get('annotations') or [])} 件\n"
                f"  tokens {res.get('usage', {}).get('total_tokens')} / "
                f"inline ${inline if inline is not None else '不明'} / "
                f"settled ${st if st is not None else '不明'} / {res['seconds']} 秒\n"
                f"  request ID {res.get('request_id')}"
            )

    known = [c["cost_usd_settled"] for c in calls if c.get("cost_usd_settled") is not None]
    summary = {
        "mode": args.mode,
        "model": args.model,
        "window": {"start": str(win.start), "end": str(win.end)},
        "seconds": round(time.monotonic() - started, 1),
        "requests": len(calls),
        "verdicts": [c["verdict"] for c in calls],
        "settled_total": round(sum(known), 6) if known else None,
        "cost_unknown": len(calls) - len(known),
        "request_ids": [c.get("request_id") for c in calls],
    }
    (run_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=1))
    print(f"\n書き出し: {run_dir}")
    print(f"判定: {summary['verdicts']}")
    print(
        f"{summary['seconds']} 秒 / 実費(settled) ${summary['settled_total']} "
        f"/ 実費不明 {summary['cost_unknown']} 件"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
