"""Jev（TypeSafe System One）への呼び出し。

**既存の `generate_structured` には押し込まない。** 別物だから。

  generate_structured   自由文を生成させ、JSON として解釈し、Schema で検証する
  Jev                   分類・採点だけを返す。**文字列は生成しない**

公式（https://typesafe.ai/blog/introducing-system-one-models-and-jev）は
「gives up string generation」と明記している。推薦理由のような自由文と、
日時のような任意の値の抽出は、**Jev では代替できない。**

## 公式で確認した仕様

  POST https://api.typesafe.ai/v1/systemone
  Authorization: Bearer <TYPESAFE_API_KEY>
  {"state": ..., "model": "jev-latest", "questions": {...}}

  -> {"model": "jev-1.13.0",
      "answers": {"<名前>": {"type": "score", "score": 1.05,
                             "probabilities": {...}, "confidence": 0.92}},
      "usage": {"input_tokens": 304, "output_tokens": 18}}

  - 質問は 1 リクエストにまとめられ、**それぞれ独立に並列評価される**
  - context 64k tokens（state + 最長の質問で 32k）
  - $0.042 / MTok（入力のみ。出力は無料）
  - 応答の `model` に**実際に答えたバージョン**が入る

## 計測とエラー処理は LLM 側と揃える

別の呼び先だが、数え方は同じにする。

  - 投げた回数は成否によらず数える
  - **使用量が取れなかった失敗を費用ゼロとしない**
  - Retry は 429 / 5xx / timeout のみ

記録先は `cost` の **Jev 専用の欄**。LLM の数には足さない。足すと
「評価を Jev に替えたら何がどう変わったか」が読めなくなる。
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

import httpx

from ai import cost
from config import Settings, get_settings
from logging_config import get_logger

logger = get_logger(__name__)

DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_MAX_ATTEMPTS = 3
_BACKOFF_SECONDS = (0.5, 1.5)

_RETRYABLE_STATUS = {408, 429, 500, 502, 503, 504}


class JevError(Exception):
    """Jev 呼び出しの失敗。"""

    def __init__(self, message: str, *, status_code: int | None = None, retryable: bool = False):
        super().__init__(message)
        self.status_code = status_code
        self.retryable = retryable


class JevConfigError(JevError):
    """キーが無いなど、投げる前に分かる失敗。**再試行しない。**"""


@dataclass(frozen=True)
class JevAnswer:
    """1 つの質問への答え。

    **confidence は正解率ではない。** 公式が明記している
    （https://docs.typesafe.ai/confidence）。確率分布がどれだけ尖っているか
    でしかなく、「自信があるが間違っている」ことはある。

    score は**水準ごとの確率で重みづけた期待値**なので、分布が違っても
    同じ値になりうる（0 と 2 が半々 = 1.0、1 に確信 = 1.0）。
    値だけで判断せず probabilities と confidence も見る。
    """

    kind: str  # "score" | "choice" | "noul"
    score: float | None = None
    choice: str | None = None
    noul: float | None = None
    probabilities: dict[str, float] = field(default_factory=dict)
    confidence: float | None = None


@dataclass(frozen=True)
class JevResponse:
    model: str
    answers: dict[str, JevAnswer]
    input_tokens: int = 0
    output_tokens: int = 0


class JevClient:
    def __init__(
        self,
        settings: Settings | None = None,
        *,
        client: httpx.Client | None = None,
        timeout: float = DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        self._settings = settings or get_settings()
        self._client = client if client is not None else httpx.Client(timeout=timeout)
        self._owns_client = client is None

    @property
    def is_configured(self) -> bool:
        return bool(self._settings.typesafe_api_key)

    def ask(
        self,
        state: str | dict | list,
        questions: dict[str, dict[str, Any]],
        *,
        max_attempts: int = DEFAULT_MAX_ATTEMPTS,
    ) -> JevResponse:
        """state に対して questions をまとめて尋ねる。

        **質問は 1 リクエストにまとめる。** 公式がそれぞれ独立に並列評価すると
        書いており、分けて投げる理由がない。
        """
        if not self._settings.typesafe_api_key:
            raise JevConfigError("TYPESAFE_API_KEY が設定されていません")
        if not questions:
            raise JevConfigError("質問がありません")

        # 工程構成上の呼び出し数。**実際に投げた回数とは別**（Retry で増える）。
        cost.record_jev_logical_call()

        url = self._settings.typesafe_base_url.rstrip("/") + "/systemone"
        payload = {
            "state": state,
            "model": self._settings.jev_model,
            "questions": questions,
        }
        headers = {
            "Authorization": f"Bearer {self._settings.typesafe_api_key}",
            "Content-Type": "application/json",
        }

        last: JevError | None = None
        for attempt in range(1, max_attempts + 1):
            try:
                res = self._client.post(url, json=payload, headers=headers)
            except httpx.TimeoutException as exc:
                # **使用量が分からない失敗。費用ゼロとは断定しない。**
                cost.record_jev_attempt(got_usage=False)
                last = JevError("Jev がタイムアウトしました", retryable=True)
                last.__cause__ = exc
            except httpx.HTTPError as exc:
                # 例外メッセージに URL とヘッダを含めない（Secret 混入を防ぐ）
                cost.record_jev_attempt(got_usage=False)
                last = JevError("Jev への接続に失敗しました", retryable=True)
                last.__cause__ = exc
            else:
                if res.status_code == 200:
                    parsed = _parse(res)
                    cost.record_jev_attempt(got_usage=True)
                    cost.record_jev_usage(
                        model=parsed.model,
                        input_tokens=parsed.input_tokens,
                        output_tokens=parsed.output_tokens,
                    )
                    return parsed
                cost.record_jev_attempt(got_usage=False)
                last = JevError(
                    f"Jev がエラーを返しました (HTTP {res.status_code})",
                    status_code=res.status_code,
                    retryable=res.status_code in _RETRYABLE_STATUS,
                )

            if not last.retryable or attempt == max_attempts:
                raise last
            cost.record_jev_retry()
            logger.warning("jev.retry attempt=%d/%d reason=%s", attempt, max_attempts, last)
            _sleep(attempt)

        raise last  # 到達しない（ループ内で必ず return か raise する）

    def close(self) -> None:
        if self._owns_client:
            self._client.close()


def _parse(res: httpx.Response) -> JevResponse:
    try:
        body = res.json()
    except ValueError as exc:
        raise JevError("Jev のレスポンス形式が想定と違います", retryable=True) from exc
    if not isinstance(body, dict):
        raise JevError("Jev のレスポンス形式が想定と違います", retryable=True)

    raw_answers = body.get("answers")
    if not isinstance(raw_answers, dict):
        raise JevError("Jev のレスポンス形式が想定と違います", retryable=True)

    answers: dict[str, JevAnswer] = {}
    for name, item in raw_answers.items():
        if not isinstance(item, dict):
            continue
        answers[name] = JevAnswer(
            kind=item.get("type") or "",
            score=_as_float(item.get("score")),
            choice=item.get("choice"),
            noul=_as_float(item.get("noul")),
            probabilities=item.get("probabilities") or {},
            confidence=_as_float(item.get("confidence")),
        )

    usage = body.get("usage") or {}
    return JevResponse(
        # **実際に答えたバージョンを残す。** jev-latest は alias で、
        # 指す先が入れ替わる。比較結果をどのモデルで得たか後から言えるようにする。
        model=body.get("model") or "",
        answers=answers,
        input_tokens=int(usage.get("input_tokens") or 0),
        output_tokens=int(usage.get("output_tokens") or 0),
    )


def _as_float(value: Any) -> float | None:
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    return None


def _sleep(attempt: int) -> None:
    index = min(attempt, len(_BACKOFF_SECONDS)) - 1
    time.sleep(_BACKOFF_SECONDS[index])


@lru_cache
def get_client() -> JevClient:
    return JevClient()


def close_client() -> None:
    if get_client.cache_info().currsize:
        get_client().close()
        get_client.cache_clear()
