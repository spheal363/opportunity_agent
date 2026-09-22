"""実験スクリプトの共通の入口（#65）。

**記録の設定漏れを、実行前に見つける。** 実際に 2 回漏らした。

  1 回目  Schema 不通過の回の usage と実費を保存していなかった
  2 回目  監査で `ORCAROUTER_INCLUDE_COST` を設定せず、実費が全件不明になった

どちらも走らせたあとで気づいた。**取り直せない**（request ID も無い）。

## 停止条件

**実費が取れない回を 0 円として数えない。** 1 回目の停止条件は
「実費が $0.50 を超えたら」だったが、`cost_usd` が None の回は加算されず、
**不明が続く限り止まらない設計だった。**

見積もりで代わりに積み、不明の件数も別に持つ。

## 並列実行中の超過

`map_parallel` が同時に投げているため、**停止を決めた時点で既に飛んでいる
リクエストは止まらない。** 上限は「これを超えたら次は投げない」であって、
「これ以上は絶対に使わない」ではない。
"""

from __future__ import annotations

import os
from datetime import datetime

# 実験では必ず実費を取る。**モデルの挙動は変わらない**（応答に欄が増えるだけ）。
REQUIRED_ENV = {"ORCAROUTER_INCLUDE_COST": "true"}

# 停止条件。超えたら**次を投げない**。飛んでいる分は止まらない。
MAX_LLM_REQUESTS = 80
MAX_SPENT_USD = 0.50
MAX_JEV_FAILURES = 3
# 実費が取れない回が続くと、費用の上限が効かなくなる。件数でも止める。
MAX_UNKNOWN_COST_RESPONSES = 20

# 実費が取れないときに代わりに積む換算。**為替 150 は仮定。**
_JPY_PER_USD = 150.0


def apply_recording_settings() -> None:
    """記録に必要な設定を入れる。**import より先に呼ぶ。**"""
    for key, value in REQUIRED_ENV.items():
        os.environ[key] = value


def check_recording_settings(settings) -> list[str]:
    """設定漏れを挙げる。**走らせる前に呼ぶ。**"""
    missing: list[str] = []
    if not settings.orcarouter_include_cost:
        missing.append(
            "ORCAROUTER_INCLUDE_COST（実費が全件「不明」になり、費用の停止条件が効かなくなる）"
        )
    return missing


class Budget:
    """使った分を数え、上限を超えたら止める。

    **実費が取れない回も数える。** 0 円として素通りさせない。
    """

    def __init__(self) -> None:
        self.llm_requests = 0
        self.actual_usd = 0.0
        self.estimated_usd = 0.0
        self.unknown_cost_responses = 0
        self.jev_failures = 0
        self.schema_failures = 0
        self.retries = 0
        self.fallbacks = 0
        self.stopped: str | None = None

    @property
    def spent_usd(self) -> float:
        """**実費 + 見積もり。** 不明を 0 として扱わない。"""
        return self.actual_usd + self.estimated_usd

    def record_response(self, *, cost_usd: float | None, estimate_jpy: float) -> None:
        if cost_usd is None:
            self.unknown_cost_responses += 1
            self.estimated_usd += estimate_jpy / _JPY_PER_USD
        else:
            self.actual_usd += cost_usd

    def check(self) -> None:
        if self.llm_requests > MAX_LLM_REQUESTS:
            self.stopped = f"LLM 実リクエストが {MAX_LLM_REQUESTS} 回を超えた"
        elif self.spent_usd > MAX_SPENT_USD:
            self.stopped = (
                f"費用が ${MAX_SPENT_USD} を超えた"
                f"（実費 ${self.actual_usd:.4f} + 見積もり ${self.estimated_usd:.4f}）"
            )
        elif self.unknown_cost_responses >= MAX_UNKNOWN_COST_RESPONSES:
            self.stopped = (
                f"実費を取れない応答が {MAX_UNKNOWN_COST_RESPONSES} 件に達した"
                "（費用の上限が効かない）"
            )
        elif self.jev_failures >= MAX_JEV_FAILURES:
            self.stopped = f"Jev が {MAX_JEV_FAILURES} 回続けて失敗した"
        if self.stopped:
            raise BudgetExceededError(self.stopped)

    def to_dict(self) -> dict:
        return {
            "llm_requests": self.llm_requests,
            "actual_usd": self.actual_usd,
            "estimated_usd_for_unknown": self.estimated_usd,
            "unknown_cost_responses": self.unknown_cost_responses,
            "schema_failures": self.schema_failures,
            "retries": self.retries,
            "fallbacks": self.fallbacks,
            "jev_failures": self.jev_failures,
            "stopped": self.stopped,
            "limits": {
                "llm_requests": MAX_LLM_REQUESTS,
                "spent_usd": MAX_SPENT_USD,
                "unknown_cost_responses": MAX_UNKNOWN_COST_RESPONSES,
                "jev_failures": MAX_JEV_FAILURES,
            },
            "note": (
                "**上限は「超えたら次を投げない」。** 並列実行中に飛んでいる"
                "リクエストは止まらないため、上限を少し超えることがある"
            ),
        }


class BudgetExceededError(RuntimeError):
    """停止条件に達した。**そこまでの記録は残す。**"""


def row_dict(row) -> dict:
    """ORM 行を、列を落とさずに dict にする。

    **手で並べると落ちる。** 実際に 2 度落とし、どちらも「取れていない」と
    報告してしまった（`eligibility` と `recommended_action`）。

    ここに置いてあるのは、**import しただけで環境変数を書き換える
    モジュールからテストを切り離す**ため。
    """
    from sqlalchemy import inspect as sa_inspect

    out = {}
    for column in sa_inspect(row).mapper.column_attrs:
        value = getattr(row, column.key)
        out[column.key] = value.isoformat() if isinstance(value, datetime) else value
    return out
