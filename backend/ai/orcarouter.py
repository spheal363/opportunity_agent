"""OrcaRouter クライアント。

OrcaRouter は OpenAI 互換のエンドポイントで、1 つのキーから複数プロバイダの
モデルを呼び分けられる。ここでは「どうやって安全・安定的に呼ぶか」だけを扱う。

  - Schema Validation と Retry は ai/llm.py（#15）
  - モデル振り分けの方針とコスト最適化は #26
  - Fallback は #25

実装上の前提（実測で確認済み）:

  - 3 モデルとも `response_format={"type":"json_object"}` に対応する。
    これを付けないと gpt-4o-mini と gemini は ```json フェンスで包んで返す。
  - gemini-2.5-flash は reasoning token を消費する。`max_tokens` が小さいと
    推論だけで枠を使い切り、content が空文字で返る。既定値を大きめに取る。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx

from config import Settings, get_settings
from logging_config import get_logger

logger = get_logger(__name__)

# reasoning 系モデルが推論で枠を使い切って空応答になるのを避ける。
DEFAULT_MAX_TOKENS = 2048
DEFAULT_TIMEOUT_SECONDS = 60.0


class ModelTier(StrEnum):
    """タスクの重さでモデルを選ぶ。

    単純な分類は CHEAP、重要な判断は POWERFUL。
    全件を高性能モデルへ投げない（コストパフォーマンスの審査項目）。
    """

    CHEAP = "cheap"
    STANDARD = "standard"
    POWERFUL = "powerful"


@dataclass(frozen=True)
class LLMUsage:
    """1 回の呼び出しの消費量。AgentRun のコスト記録（#26）の入力になる。"""

    model: str
    tier: ModelTier
    prompt_tokens: int
    completion_tokens: int
    reasoning_tokens: int
    total_tokens: int
    latency_ms: int


@dataclass(frozen=True)
class LLMResponse:
    content: str
    usage: LLMUsage


class LLMError(Exception):
    """LLM 呼び出しの失敗。"""


class LLMConfigError(LLMError):
    """API キーやモデル ID が設定されていない。"""


class LLMRequestError(LLMError):
    """リクエストが失敗した。

    retryable が True のものだけ再試行の対象にする（#24）。
    """

    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class EmptyResponseError(LLMRequestError):
    """content が空で返った。

    reasoning 系モデルで max_tokens が不足したときに起きる。
    再試行の価値があるので retryable 扱いにする。
    """

    def __init__(self, message: str):
        super().__init__(message, retryable=True)


# 再試行する価値がある HTTP ステータス。
_RETRYABLE_STATUS = {408, 409, 425, 429, 500, 502, 503, 504}


class OrcaRouterClient:
    """OrcaRouter への薄いクライアント。

    OpenAI SDK を足さず httpx で直接叩く。依存を増やさず、
    タイムアウトとエラー分類を自分たちで持てるようにするため（Reliability）。
    """

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._settings = settings or get_settings()
        self._timeout = timeout
        self._client = client
        self._owns_client = client is None

    # -- 設定 ------------------------------------------------------------

    @property
    def is_configured(self) -> bool:
        """キーとベース URL が揃っているか。

        AGENT_STUB_MODE で動かすときは未設定でも起動できる必要がある。
        """
        return bool(self._settings.orcarouter_api_key and self._settings.orcarouter_base_url)

    def model_for(self, tier: ModelTier) -> str:
        model = {
            ModelTier.CHEAP: self._settings.llm_model_cheap,
            ModelTier.STANDARD: self._settings.llm_model_standard,
            ModelTier.POWERFUL: self._settings.llm_model_powerful,
        }[tier]
        if not model:
            raise LLMConfigError(f"LLM_MODEL_{tier.upper()} が設定されていません")
        return model

    def _require_config(self) -> None:
        if not self._settings.orcarouter_api_key:
            raise LLMConfigError("ORCAROUTER_API_KEY が設定されていません")
        if not self._settings.orcarouter_base_url:
            raise LLMConfigError("ORCAROUTER_BASE_URL が設定されていません")

    def _http(self) -> httpx.Client:
        if self._client is None:
            self._client = httpx.Client(timeout=self._timeout)
        return self._client

    # -- 呼び出し --------------------------------------------------------

    def chat(
        self,
        messages: list[dict[str, str]],
        *,
        tier: ModelTier = ModelTier.STANDARD,
        json_mode: bool = True,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        temperature: float | None = None,
    ) -> LLMResponse:
        """1 回の chat completion。Retry はしない（#15 の責務）。

        json_mode=True のとき response_format を付けて JSON を強制する。
        フェンス付きで返るモデルがあるため、原則 True のまま使う。
        """
        self._require_config()
        model = self.model_for(tier)

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "max_tokens": max_tokens,
        }
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        if temperature is not None:
            payload["temperature"] = temperature

        url = f"{self._settings.orcarouter_base_url.rstrip('/')}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._settings.orcarouter_api_key}",
            "Content-Type": "application/json",
        }

        started = time.perf_counter()
        try:
            res = self._http().post(url, json=payload, headers=headers)
        except httpx.TimeoutException as exc:
            raise LLMRequestError(f"LLM がタイムアウトしました: {model}", retryable=True) from exc
        except httpx.HTTPError as exc:
            # 例外メッセージに URL とヘッダを含めない（Secret 混入を防ぐ）
            raise LLMRequestError(f"LLM への接続に失敗しました: {model}", retryable=True) from exc
        latency_ms = int((time.perf_counter() - started) * 1000)

        if res.status_code != 200:
            raise LLMRequestError(
                f"LLM がエラーを返しました: {model} (HTTP {res.status_code})",
                status_code=res.status_code,
                retryable=res.status_code in _RETRYABLE_STATUS,
            )

        return self._parse(res, model=model, tier=tier, latency_ms=latency_ms)

    def _parse(
        self, res: httpx.Response, *, model: str, tier: ModelTier, latency_ms: int
    ) -> LLMResponse:
        try:
            body = res.json()
            choice = body["choices"][0]
            content = choice["message"].get("content") or ""
        except (ValueError, KeyError, IndexError) as exc:
            raise LLMRequestError(
                f"LLM のレスポンス形式が想定と違います: {model}", retryable=True
            ) from exc

        usage_body = body.get("usage") or {}
        details = usage_body.get("completion_tokens_details") or {}
        usage = LLMUsage(
            model=model,
            tier=tier,
            prompt_tokens=usage_body.get("prompt_tokens", 0),
            completion_tokens=usage_body.get("completion_tokens", 0),
            reasoning_tokens=details.get("reasoning_tokens", 0),
            total_tokens=usage_body.get("total_tokens", 0),
            latency_ms=latency_ms,
        )

        # Secret とプロンプト本文は出さない。追跡に必要な情報だけ残す。
        logger.info(
            "llm.call model=%s tier=%s tokens=%d reasoning=%d latency=%dms",
            usage.model,
            usage.tier,
            usage.total_tokens,
            usage.reasoning_tokens,
            usage.latency_ms,
        )

        if not content.strip():
            raise EmptyResponseError(
                f"LLM が空の応答を返しました: {model}"
                f"（reasoning={usage.reasoning_tokens} tokens。max_tokens 不足の可能性）"
            )
        return LLMResponse(content=content, usage=usage)

    def close(self) -> None:
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None

    def __enter__(self) -> OrcaRouterClient:
        return self

    def __exit__(self, *_: object) -> None:
        self.close()
