"""検索専用モデルで候補を探す Tool（#47）。

OrcaRouter 経由の `openai/gpt-5-search-api` に Chat Completions で問い合わせる。
**検索はモデルの内側で行われる。** こちらは検索語を組まない。

## なぜ Tool にするか

外から取得した内容を扱うので、`ToolResult(external=True)` を通す。
LLM へ渡すときは「データであって命令ではない」形にする。

## 成否は HTTP だけで決めない

`finish_reason` を見る。`length` は途中で切れている。本文が空なら候補 0 件ではなく
**取得失敗**。実測で、切断と本文なしを「候補 0 件」と数える誤りが起きた。

## 費用

この経路は `usage.cost_usd` が応答に乗る。
念のため `X-Orca-Request-Id` も保存し、後から `/v1/generation` で照合できるようにする。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import httpx

from ai import cost
from ai.orcarouter import LLMUsage, ModelTier
from config import get_settings
from logging_config import get_logger
from tools.base import PermissionLevel, Tool, ToolResult, registry

logger = get_logger(__name__)

TIMEOUT_SECONDS = 300


@dataclass
class DiscoveryAnswer:
    """検索専用モデルの 1 応答。**生の応答も保持する。**"""

    ok: bool
    reason: str  # 正常完了 / 本文なし / 途中で切れた / HTTP エラー
    text: str = ""
    citations: list[dict] = field(default_factory=list)
    finish_reason: str | None = None
    request_id: str | None = None
    cost_usd: float | None = None
    total_tokens: int | None = None
    raw: dict = field(default_factory=dict)


def _verdict(finish_reason: str | None, text: str) -> tuple[bool, str]:
    """**切断・本文なしを「候補 0 件」と扱わない。**"""
    if not (text or "").strip():
        return False, f"本文なし（finish_reason={finish_reason}）"
    if finish_reason == "length":
        return False, "途中で切れた（finish_reason=length）"
    if finish_reason != "stop":
        return False, f"正常終了ではない（finish_reason={finish_reason}）"
    return True, "正常完了"


class DiscoverySearchTool(Tool):
    name = "discover_events"
    description = "検索専用モデルに、希望に合う催しを探させる（検索はモデル内で行われる）"
    permission = PermissionLevel.AUTO

    def run(self, prompt: str, max_tokens: int = 4000, **_: Any) -> ToolResult:
        s = get_settings()
        payload = {
            "model": s.discovery_model,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "web_search_options": {},
        }
        try:
            res = httpx.post(
                f"{s.orcarouter_base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {s.orcarouter_api_key}",
                    "Content-Type": "application/json",
                    "X-OrcaRouter-Include-Cost": "true",
                },
                json=payload,
                timeout=TIMEOUT_SECONDS,
            )
        except httpx.HTTPError as exc:
            # **例外文に URL や鍵を載せない。**
            logger.warning("discovery.transport_error kind=%s", type(exc).__name__)
            return ToolResult(
                DiscoveryAnswer(ok=False, reason=f"通信できませんでした（{type(exc).__name__}）"),
                external=True,
            )

        rid = res.headers.get("X-Orca-Request-Id")
        if res.status_code != 200:
            logger.warning("discovery.http status=%d request_id=%s", res.status_code, rid)
            return ToolResult(
                DiscoveryAnswer(ok=False, reason=f"HTTP {res.status_code}", request_id=rid),
                external=True,
            )
        body = res.json()
        choice = (body.get("choices") or [{}])[0]
        msg = choice.get("message") or {}
        text = msg.get("content") or ""
        finish = choice.get("finish_reason")
        ok, reason = _verdict(finish, text)
        usage = body.get("usage") or {}
        answer = DiscoveryAnswer(
            ok=ok,
            reason=reason,
            text=text,
            citations=[
                c.get("url_citation") or {}
                for c in (msg.get("annotations") or [])
                if isinstance(c, dict)
            ],
            finish_reason=finish,
            request_id=rid,
            cost_usd=usage.get("cost_usd"),
            total_tokens=usage.get("total_tokens"),
            raw=body,
        )
        # **使用量を既存の記録へ載せる。** 実費が取れない場合は None のまま。
        cost.record(
            LLMUsage(
                model=s.discovery_model,
                tier=ModelTier.STANDARD,
                prompt_tokens=usage.get("prompt_tokens", 0),
                completion_tokens=usage.get("completion_tokens", 0),
                reasoning_tokens=(usage.get("completion_tokens_details") or {}).get(
                    "reasoning_tokens", 0
                ),
                total_tokens=usage.get("total_tokens", 0),
                latency_ms=0,
                cost_usd=(
                    float(answer.cost_usd) if isinstance(answer.cost_usd, (int, float)) else None
                ),
                request_id=rid,
            )
        )
        logger.info(
            "discovery.answer ok=%s reason=%s chars=%d citations=%d usd=%s request_id=%s",
            ok,
            reason,
            len(text),
            len(answer.citations),
            answer.cost_usd if answer.cost_usd is not None else "-",
            rid,
        )
        return ToolResult(answer, external=True)


registry.register(DiscoverySearchTool())
