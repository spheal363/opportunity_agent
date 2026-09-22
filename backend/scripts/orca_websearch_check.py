"""OrcaRouter 経由で、モデル内蔵の Web 検索が使えるかの最小検証（#47）。

**本番構成は変更しない。** 独立したスクリプト。

公式仕様（docs.orcarouter.ai）で確認した 2 つの経路を、実際に叩いて確かめる。

  1. Chat Completions + `web_search_options`
  2. Responses API + `tools: [{"type": "web_search"}]`

**通常呼び出しと検索付き呼び出しを必ず対で実行する。** 差が出なければ、
「検索が効いた」とは言えない。
"""

from __future__ import annotations

import argparse
import json
import sys

from scripts._experiment import apply_recording_settings

apply_recording_settings()

import httpx  # noqa: E402

from config import get_settings  # noqa: E402

PROMPT = (
    "2026年10月に東京都内で現地参加できる、ハウスまたはテクノのクラブイベントを3件。"
    "それぞれ 開催日 / 会場 / 出典URL を挙げてください。"
    "確認できないものは挙げないでください。"
)


def _post(path: str, payload: dict) -> tuple[int, dict, str]:
    s = get_settings()
    r = httpx.post(
        f"{s.orcarouter_base_url}{path}",
        headers={
            "Authorization": f"Bearer {s.orcarouter_api_key}",
            "Content-Type": "application/json",
            "X-OrcaRouter-Include-Cost": "true",
        },
        json=payload,
        timeout=300,
    )
    try:
        body = r.json()
    except Exception:  # noqa: BLE001
        body = {"raw": r.text[:600]}
    return r.status_code, body, r.headers.get("X-Orca-Request-Id", "-")


def _chat(model: str, *, with_search: bool) -> None:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": PROMPT}],
        "max_tokens": 1200,
    }
    if with_search:
        payload["web_search_options"] = {}
    label = "検索あり" if with_search else "検索なし"
    code, body, rid = _post("/chat/completions", payload)
    print(f"\n--- Chat Completions / {model} / {label} ---")
    print(f"HTTP {code}  request-id {rid}")
    if code != 200:
        print("  応答:", json.dumps(body, ensure_ascii=False)[:500])
        return
    msg = body["choices"][0]["message"]
    usage = body.get("usage") or {}
    ann = msg.get("annotations") or []
    print(f"  実費 ${usage.get('cost_usd')}  tokens {usage.get('total_tokens')}")
    print(f"  引用(annotations) {len(ann)} 件")
    for a in ann[:5]:
        cit = a.get("url_citation") or {}
        print(f"     - {(cit.get('title') or '')[:48]} | {(cit.get('url') or '')[:74]}")
    print("  本文:", (msg.get("content") or "")[:700].replace("\n", " "))


def _responses(model: str, *, with_search: bool) -> None:
    payload = {"model": model, "input": PROMPT, "max_output_tokens": 1200}
    if with_search:
        payload["tools"] = [{"type": "web_search"}]
    label = "検索あり" if with_search else "検索なし"
    code, body, rid = _post("/responses", payload)
    print(f"\n--- Responses API / {model} / {label} ---")
    print(f"HTTP {code}  request-id {rid}")
    if code != 200:
        print("  応答:", json.dumps(body, ensure_ascii=False)[:500])
        return
    kinds = [o.get("type") for o in body.get("output") or []]
    print("  output の種類:", kinds)
    usage = body.get("usage") or {}
    print(f"  実費 ${usage.get('cost_usd')}  tokens {usage.get('total_tokens')}")
    text = []
    for o in body.get("output") or []:
        for c in o.get("content") or []:
            if c.get("type") in ("output_text", "text"):
                text.append(c.get("text") or "")
    print("  本文:", " ".join(text)[:700].replace("\n", " "))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true")
    ap.add_argument("--chat-model", default="openai/gpt-5-search-api")
    ap.add_argument("--resp-model", default="openai/gpt-5")
    args = ap.parse_args()
    print("最小検証: 通常呼び出しと検索付き呼び出しを対で実行します（各 2 回 = 計 4 回）")
    if not args.confirm:
        print("--confirm を付けると実行します")
        return 0
    _chat(args.chat_model, with_search=False)
    _chat(args.chat_model, with_search=True)
    _responses(args.resp_model, with_search=False)
    _responses(args.resp_model, with_search=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
