"""LLM 呼び出しのコスト記録。

**`generate_structured` が唯一の LLM 呼び出し口**なので、そこで消費量を拾う。
各 AI 関数のシグネチャを変えずに済む。

集計は `contextvars` で run ごとに分離する。ただし **ThreadPoolExecutor は
context を自動で引き継がない**ため、`ai/concurrency.map_parallel` 側で明示的に
コピーしている。これを忘れるとワーカーの消費が黙って落ちる。
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field

from ai.orcarouter import LLMUsage, ModelTier

# 1M トークンあたりの円換算。
#
# **これは見積もりであって請求額ではない。** 主催者から実単価の提供が無いため、
# 各モデルの公開価格をもとに置いている。実単価が分かれば差し替える。
# 「いくらかかったか」ではなく「高いモデルをどれだけ使ったか」を見るための値。
#
# 環境変数では持たせていない。値の出どころをコードに残したいため。
_JPY_PER_1M_TOKENS: dict[str, tuple[float, float]] = {
    # model                          (input, output)
    "openai/gpt-4o-mini": (23.0, 90.0),
    "google/gemini-2.5-flash": (45.0, 375.0),
    "anthropic/claude-opus-4.7": (2250.0, 11250.0),
}

# 上の表に無いモデルに使う値。STANDARD 相当で見積もる。
_FALLBACK_RATE = (45.0, 375.0)


def estimate_jpy(usage: LLMUsage) -> float:
    """1 回の呼び出しの見積もり額。

    reasoning token は completion に含まれる（provider の集計に従う）。
    """
    rate_in, rate_out = _JPY_PER_1M_TOKENS.get(usage.model, _FALLBACK_RATE)
    return (usage.prompt_tokens * rate_in + usage.completion_tokens * rate_out) / 1_000_000


@dataclass
class CostTracker:
    """1 回の Agent Run の消費量。**スレッドから同時に書かれる。**"""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    calls: int = 0
    total_tokens: int = 0
    reasoning_tokens: int = 0
    jpy: float = 0.0
    # tier ごとの呼び出し回数。モデル振り分け（#26-b）を見せるのに使う。
    calls_by_tier: dict[str, int] = field(default_factory=dict)

    def record(self, usage: LLMUsage) -> None:
        with self._lock:
            self.calls += 1
            self.total_tokens += usage.total_tokens
            self.reasoning_tokens += usage.reasoning_tokens
            self.jpy += estimate_jpy(usage)
            tier = usage.tier.value if isinstance(usage.tier, ModelTier) else str(usage.tier)
            self.calls_by_tier[tier] = self.calls_by_tier.get(tier, 0) + 1

    @property
    def expensive_calls(self) -> int:
        """高性能モデルの呼び出し回数。**全件を powerful へ投げていない証拠**。"""
        return self.calls_by_tier.get(ModelTier.POWERFUL.value, 0)


_current: ContextVar[CostTracker | None] = ContextVar("cost_tracker", default=None)


@contextmanager
def track() -> Iterator[CostTracker]:
    """この中で起きた LLM 呼び出しの消費量を集める。"""
    tracker = CostTracker()
    token = _current.set(tracker)
    try:
        yield tracker
    finally:
        _current.reset(token)


def snapshot() -> CostTracker | None:
    """ワーカースレッドへ引き継ぐ値。

    **引き継ぐものをここで決める。** `map_parallel` が context 全体を
    複製すると、将来ここ以外の ContextVar（認証情報やトレース ID など）まで
    気づかれずにワーカーへ流れる。渡してよいものを明示する。
    """
    return _current.get()


@contextmanager
def restore(tracker: CostTracker | None) -> Iterator[None]:
    """`snapshot()` の値をこのスレッドへ復元する。"""
    token = _current.set(tracker)
    try:
        yield
    finally:
        _current.reset(token)


def current() -> CostTracker | None:
    """いま集計中の tracker。`track()` の外なら None。"""
    return _current.get()


def record(usage: LLMUsage) -> None:
    """消費量を記録する。`track()` の外で呼ばれたら何もしない。"""
    tracker = _current.get()
    if tracker is not None:
        tracker.record(usage)
