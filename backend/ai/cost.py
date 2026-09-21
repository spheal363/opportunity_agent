"""LLM 呼び出しのコスト記録。

**`generate_structured` が唯一の LLM 呼び出し口**なので、そこで消費量を拾う。
各 AI 関数のシグネチャを変えずに済む。

集計は `contextvars` で run ごとに分離する。ただし **ThreadPoolExecutor は
context を自動で引き継がない**ため、`ai/concurrency.map_parallel` 側で明示的に
コピーしている。これを忘れるとワーカーの消費が黙って落ちる。
"""

from __future__ import annotations

import threading
import time
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


# Jev（TypeSafe System One）の公式単価。
# https://docs.typesafe.ai/models — $42 / 1B tokens = $0.042 / MTok、出力は無料。
#
# **円に換算しない。** 為替レートを勝手に置くと、公式単価という確かな値に
# 推測を混ぜることになる。LLM 側の円見積もりとは別の欄で持つ。
_JEV_USD_PER_1M_INPUT_TOKENS = 0.042


@dataclass
class JevUsage:
    """Jev の使用量。**LLM と混ぜない。**

    同じ「評価」という工程でも、呼び先も課金体系も違う。合算すると
    A/B 比較（評価を LLM から Jev へ替えたときの差）が読めなくなる。

    usd は**公式単価と実トークン数の積**であって、請求額ではない。
    無料枠が適用されればこの額は請求されない。
    """

    logical_calls: int = 0
    request_attempts: int = 0
    usage_records: int = 0
    attempts_without_usage: int = 0
    retries: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    usd: float = 0.0
    # confidence が閾値を下回り、既存 LLM へ回した回数。
    # **その費用は LLM 側の欄に乗る。** Jev に替えた分だけ安くなる、とは限らない。
    #
    # **呼べなかった回数はここに入れない。** 混ぜると、A/B 比較で見たい
    # 「Jev の確信度が低くて LLM へ回った率」に接続エラーが紛れ込む。
    # フォールバック率は C の費用削減幅を決める値なので、濁らせない。
    low_confidence_fallbacks: int = 0
    # Jev を呼べなかった・応答が使えなかった回数（timeout / HTTP / 形式異常）。
    # こちらも LLM へ回るが、**原因が違う。**
    hard_failures: int = 0
    # 実際に応答を返したモデルのバージョン。alias（jev-latest）は解決後の値が返る。
    models: dict[str, int] = field(default_factory=dict)


@dataclass
class StepUsage:
    """1 工程ぶんの使用量。**数の意味を混ぜない。**

    logical_calls   generate_structured を呼んだ回数（工程構成上の数）
    request_attempts 外部へリクエストを投げた回数（Retry / Fallback を含む）
    usage_records   使用量を取得できた応答の数
    attempts_without_usage
                    投げたが使用量が分からなかった回数。
                    **費用ゼロとは限らない**（timeout / 接続失敗など）
    """

    logical_calls: int = 0
    request_attempts: int = 0
    usage_records: int = 0
    attempts_without_usage: int = 0
    retries: int = 0
    fallbacks: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    reasoning_tokens: int = 0
    jpy: float = 0.0
    # OrcaRouter が返した**実費**（USD）。見積もりとは別に持つ。
    # `X-OrcaRouter-Include-Cost` を送った呼び出しだけ入る。
    actual_usd: float = 0.0
    # 実費を返さなかった応答の数。**費用ゼロではない。** 確定額を引くには
    # このぶんだけ GET /v1/generation?id= の照会が要る。
    responses_without_actual_cost: int = 0
    # 工程全体の経過時間。**並列呼び出しの時間の合計ではない。**
    elapsed_ms: int = 0
    calls_by_tier: dict[str, int] = field(default_factory=dict)
    # Jev の分。**LLM の数には足さない。**
    jev: JevUsage = field(default_factory=JevUsage)

    def to_dict(self) -> dict:
        """DB へ保存する形。入れ子の dataclass も展開する。

        `vars()` をそのまま使うと `jev` が dataclass のまま残り、
        JSON 化で落ちる。
        """
        out = {k: v for k, v in vars(self).items() if k != "jev"}
        out["jev"] = vars(self.jev)
        return out


@dataclass
class CostTracker:
    """1 回の Agent Run の消費量。**スレッドから同時に書かれる。**"""

    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)
    by_step: dict[str, StepUsage] = field(default_factory=dict)
    # 検索 provider の使用量。**料金は未確認**なので回数だけ持つ。
    search_calls: int = 0
    # 本文取得を**試した** URL 数と、**取れた**数。
    # **試行と成功を分ける。** 取れなかった分も使用量としては発生している。
    extract_calls: int = 0
    extract_successes: int = 0
    # 候補が落ちた理由別の件数
    dropped: dict[str, int] = field(default_factory=dict)
    # 最終結果の受付状況の内訳
    final_availability: dict[str, int] = field(default_factory=dict)
    # どの評価器が結果を出したか（"llm" / "jev"）と、実際のモデルバージョン。
    # **比較結果をどの構成で得たか、後から言えるようにする。**
    evaluator: str | None = None
    evaluator_model: str | None = None
    # 確定額を後から引くための ID（GET /v1/generation?id=）。
    # **捨てると、その run の請求額は二度と確かめられない。**
    request_ids: list[str] = field(default_factory=list)
    # どの構成で走ったか。**比較の記録に構成が無いと、後から読めない。**
    search_provider: str | None = None
    page_fetcher: str | None = None
    search_pipeline: str | None = None

    # --- 工程を跨いだ合計（既存の互換用）-----------------------------------

    @property
    def usage_records(self) -> int:
        return sum(u.usage_records for u in self.by_step.values())

    @property
    def total_tokens(self) -> int:
        return sum(u.prompt_tokens + u.completion_tokens for u in self.by_step.values())

    @property
    def reasoning_tokens(self) -> int:
        return sum(u.reasoning_tokens for u in self.by_step.values())

    @property
    def jpy(self) -> float:
        return sum(u.jpy for u in self.by_step.values())

    @property
    def calls_by_tier(self) -> dict[str, int]:
        merged: dict[str, int] = {}
        for u in self.by_step.values():
            for tier, n in u.calls_by_tier.items():
                merged[tier] = merged.get(tier, 0) + n
        return merged

    @property
    def actual_usd(self) -> float:
        """OrcaRouter が返した実費の合計（USD）。**円の見積もりとは別。**"""
        return sum(u.actual_usd for u in self.by_step.values())

    @property
    def responses_without_actual_cost(self) -> int:
        """実費が返らなかった応答の数。**費用ゼロではない。**"""
        return sum(u.responses_without_actual_cost for u in self.by_step.values())

    @property
    def jev_usd(self) -> float:
        """Jev の見積もり額（ドル）。**円の見積もりとは別。**"""
        return sum(u.jev.usd for u in self.by_step.values())

    @property
    def jev_request_attempts(self) -> int:
        return sum(u.jev.request_attempts for u in self.by_step.values())

    @property
    def expensive_calls(self) -> int:
        """高性能モデルの呼び出し回数。**全件を powerful へ投げていない証拠**。"""
        return self.calls_by_tier.get(ModelTier.POWERFUL.value, 0)

    # --- 記録 ---------------------------------------------------------------

    def _slot(self, step: str) -> StepUsage:
        return self.by_step.setdefault(step, StepUsage())

    def record(self, usage: LLMUsage, *, step: str | None = None) -> None:
        """**Schema 検証の前に呼ぶ。** 応答が返った時点で課金は発生している。

        出力が Schema を通らなくても、その呼び出しの費用は消えない。
        """
        with self._lock:
            u = self._slot(step or current_step())
            u.usage_records += 1
            # **実費と request ID を捨てない。** 後から確定額を引くのに要る。
            if usage.cost_usd is not None:
                u.actual_usd += usage.cost_usd
            else:
                u.responses_without_actual_cost += 1
            if usage.request_id:
                self.request_ids.append(usage.request_id)
            u.prompt_tokens += usage.prompt_tokens
            u.completion_tokens += usage.completion_tokens
            u.reasoning_tokens += usage.reasoning_tokens
            u.jpy += estimate_jpy(usage)
            tier = usage.tier.value if isinstance(usage.tier, ModelTier) else str(usage.tier)
            u.calls_by_tier[tier] = u.calls_by_tier.get(tier, 0) + 1

    def record_logical_call(self) -> None:
        with self._lock:
            self._slot(current_step()).logical_calls += 1

    def record_attempt(self, *, got_usage: bool) -> None:
        """外部へ 1 回投げたことを記録する。

        **使用量が取れなかった回も数える。** timeout や接続失敗は usage が
        付かないが、投げたこと自体は起きている。**費用ゼロとは断定しない。**
        """
        with self._lock:
            u = self._slot(current_step())
            u.request_attempts += 1
            if not got_usage:
                u.attempts_without_usage += 1

    def record_retry(self) -> None:
        with self._lock:
            self._slot(current_step()).retries += 1

    def record_fallback(self) -> None:
        with self._lock:
            self._slot(current_step()).fallbacks += 1

    # --- Jev ----------------------------------------------------------------
    #
    # **LLM と同じ意味の数を、別の欄に持つ。** 記録の仕方は揃える
    # （試行は成否によらず数える／使用量が取れない失敗も費用ゼロとしない）。

    def record_jev_logical_call(self) -> None:
        with self._lock:
            self._slot(current_step()).jev.logical_calls += 1

    def record_jev_attempt(self, *, got_usage: bool) -> None:
        with self._lock:
            j = self._slot(current_step()).jev
            j.request_attempts += 1
            if not got_usage:
                j.attempts_without_usage += 1

    def record_jev_retry(self) -> None:
        with self._lock:
            self._slot(current_step()).jev.retries += 1

    def record_jev_usage(self, *, model: str, input_tokens: int, output_tokens: int) -> None:
        with self._lock:
            j = self._slot(current_step()).jev
            j.usage_records += 1
            j.input_tokens += input_tokens
            j.output_tokens += output_tokens
            # 出力は無料。入力ぶんだけを積む。
            j.usd += input_tokens * _JEV_USD_PER_1M_INPUT_TOKENS / 1_000_000
            j.models[model] = j.models.get(model, 0) + 1

    def record_jev_low_confidence(self) -> None:
        with self._lock:
            self._slot(current_step()).jev.low_confidence_fallbacks += 1

    def record_jev_hard_failure(self) -> None:
        """**確信が持てなかったのではなく、呼べなかった。** 別に数える。"""
        with self._lock:
            self._slot(current_step()).jev.hard_failures += 1

    def record_elapsed(self, step: str, ms: int) -> None:
        with self._lock:
            self._slot(step).elapsed_ms += ms

    def record_search(self) -> None:
        with self._lock:
            self.search_calls += 1

    def record_extract(self, n: int = 1) -> None:
        with self._lock:
            self.extract_calls += n

    def record_extract_success(self, n: int = 1) -> None:
        with self._lock:
            self.extract_successes += n

    def record_dropped(self, reason: str, n: int = 1) -> None:
        with self._lock:
            self.dropped[reason] = self.dropped.get(reason, 0) + n

    def record_evaluator(self, evaluator: str, model: str | None) -> None:
        with self._lock:
            self.evaluator = evaluator
            self.evaluator_model = model

    def record_final_availability(self, values: list[str]) -> None:
        with self._lock:
            for v in values:
                self.final_availability[v] = self.final_availability.get(v, 0) + 1

    def to_dict(self) -> dict:
        """DB へ保存する形。"""
        with self._lock:
            return {
                "by_step": {k: v.to_dict() for k, v in self.by_step.items()},
                "search_calls": self.search_calls,
                "extract_calls": self.extract_calls,
                "extract_successes": self.extract_successes,
                "dropped": dict(self.dropped),
                "final_availability": dict(self.final_availability),
                "evaluator": self.evaluator,
                "evaluator_model": self.evaluator_model,
                "search_provider": self.search_provider,
                "page_fetcher": self.page_fetcher,
                "search_pipeline": self.search_pipeline,
                "actual_usd": self.actual_usd,
                "responses_without_actual_cost": self.responses_without_actual_cost,
                # **確定額を引くための ID。** 捨てると後から確かめられない。
                "request_ids": list(self.request_ids),
            }


_current: ContextVar[CostTracker | None] = ContextVar("cost_tracker", default=None)
# いまどの工程を実行中か。並列ワーカーへは `snapshot()` / `restore()` で引き継ぐ。
_step: ContextVar[str] = ContextVar("cost_step", default="unknown")


def current_step() -> str:
    return _step.get()


@contextmanager
def step(name: str) -> Iterator[None]:
    """この中の LLM 呼び出しを `name` の工程として数える。

    **工程全体の経過時間も測る。** 並列呼び出しの時間の合計ではなく、
    入ってから出るまでの実時間。
    """
    token = _step.set(name)
    started = time.monotonic()
    try:
        yield
    finally:
        elapsed_ms = int((time.monotonic() - started) * 1000)
        tracker = _current.get()
        if tracker is not None:
            tracker.record_elapsed(name, elapsed_ms)
        _step.reset(token)


@contextmanager
def track() -> Iterator[CostTracker]:
    """この中で起きた LLM 呼び出しの消費量を集める。

    **どの構成で走ったかも一緒に残す。** 比較（#65）の記録に構成が無いと、
    後から「これはどの組み合わせの数字か」が言えなくなる。
    """
    from config import get_settings  # 循環 import を避けるためここで読む

    settings = get_settings()
    tracker = CostTracker(
        search_provider=settings.search_provider,
        page_fetcher=settings.page_fetcher,
        search_pipeline=settings.search_pipeline,
    )
    token = _current.set(tracker)
    try:
        yield tracker
    finally:
        _current.reset(token)


def snapshot() -> tuple[CostTracker | None, str]:
    """ワーカースレッドへ引き継ぐ値。

    **引き継ぐものをここで決める。** `map_parallel` が context 全体を
    複製すると、将来ここ以外の ContextVar（認証情報やトレース ID など）まで
    気づかれずにワーカーへ流れる。渡してよいものを明示する。

    **工程名も一緒に運ぶ。** 運ばないとワーカー内の記録が "unknown" に落ちる。
    """
    return _current.get(), _step.get()


@contextmanager
def restore(snap: tuple[CostTracker | None, str]) -> Iterator[None]:
    """`snapshot()` の値をこのスレッドへ復元する。"""
    tracker, step_name = snap
    tracker_token = _current.set(tracker)
    step_token = _step.set(step_name)
    try:
        yield
    finally:
        _step.reset(step_token)
        _current.reset(tracker_token)


def current() -> CostTracker | None:
    """いま集計中の tracker。`track()` の外なら None。"""
    return _current.get()


def record(usage: LLMUsage) -> None:
    """消費量を記録する。`track()` の外で呼ばれたら何もしない。"""
    tracker = _current.get()
    if tracker is not None:
        tracker.record(usage)


def _to_tracker(method: str, *args, **kwargs) -> None:
    """`track()` の中でだけ記録する。外では何もしない。"""
    tracker = _current.get()
    if tracker is not None:
        getattr(tracker, method)(*args, **kwargs)


def record_logical_call() -> None:
    """`generate_structured` を 1 回呼んだ。**実際に投げた回数とは別。**"""
    _to_tracker("record_logical_call")


def record_attempt(*, got_usage: bool) -> None:
    """外部へ 1 回投げた。使用量が取れなかった回も数える。"""
    _to_tracker("record_attempt", got_usage=got_usage)


def record_retry() -> None:
    _to_tracker("record_retry")


def record_fallback() -> None:
    _to_tracker("record_fallback")


def record_search() -> None:
    """検索 provider を 1 回叩いた。**料金は未確認**なので回数だけ。"""
    _to_tracker("record_search")


def record_extract(n: int = 1) -> None:
    """本文取得を n 件ぶん叩いた。"""
    _to_tracker("record_extract", n)


def record_dropped(reason: str, n: int = 1) -> None:
    """候補が落ちた理由を数える。"""
    _to_tracker("record_dropped", reason, n)


def record_final_availability(values: list[str]) -> None:
    _to_tracker("record_final_availability", values)


def record_jev_logical_call() -> None:
    _to_tracker("record_jev_logical_call")


def record_jev_attempt(*, got_usage: bool) -> None:
    _to_tracker("record_jev_attempt", got_usage=got_usage)


def record_jev_retry() -> None:
    _to_tracker("record_jev_retry")


def record_jev_usage(*, model: str, input_tokens: int, output_tokens: int) -> None:
    _to_tracker(
        "record_jev_usage",
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
    )


def record_jev_low_confidence() -> None:
    _to_tracker("record_jev_low_confidence")


def record_evaluator(evaluator: str, model: str | None = None) -> None:
    _to_tracker("record_evaluator", evaluator, model)


def record_extract_success(n: int = 1) -> None:
    _to_tracker("record_extract_success", n)


def record_jev_hard_failure() -> None:
    _to_tracker("record_jev_hard_failure")
