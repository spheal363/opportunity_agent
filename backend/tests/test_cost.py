"""コスト記録（#26-a）。

**測定であって最適化ではない。** 品質・速度を変えたときに、コストが
どう動いたかを比べられるようにするための土台。
"""

import threading

import pytest

from ai import cost
from ai.concurrency import map_parallel
from ai.orcarouter import LLMUsage, ModelTier


def _usage(**overrides) -> LLMUsage:
    base = {
        "model": "google/gemini-2.5-flash",
        "tier": ModelTier.STANDARD,
        "prompt_tokens": 1000,
        "completion_tokens": 500,
        "reasoning_tokens": 200,
        "total_tokens": 1500,
        "latency_ms": 1000,
    }
    base.update(overrides)
    return LLMUsage(**base)


# --- 見積もり -------------------------------------------------------------


def test_estimate_uses_input_and_output_rates():
    """入力と出力で単価が違う。"""
    jpy = cost.estimate_jpy(_usage(prompt_tokens=1_000_000, completion_tokens=0))
    assert jpy == pytest.approx(45.0)

    jpy = cost.estimate_jpy(_usage(prompt_tokens=0, completion_tokens=1_000_000))
    assert jpy == pytest.approx(375.0)


def test_powerful_is_much_more_expensive():
    """**この差が「全件を powerful へ投げない」判断の根拠になる。**"""
    cheap = cost.estimate_jpy(_usage(model="openai/gpt-4o-mini"))
    standard = cost.estimate_jpy(_usage(model="google/gemini-2.5-flash"))
    powerful = cost.estimate_jpy(_usage(model="anthropic/claude-opus-4.7"))

    assert cheap < standard < powerful
    assert powerful > standard * 10


def test_unknown_model_falls_back_to_a_rate():
    """表に無いモデルでも 0 円にしない。0 だと「無料で動いた」ように見える。"""
    assert cost.estimate_jpy(_usage(model="unknown/model")) > 0


# --- 集計 -----------------------------------------------------------------


def test_records_nothing_outside_track():
    """`track()` の外では何もしない。例外にもしない。"""
    cost.record(_usage())  # 落ちなければよい
    assert cost.current() is None


def test_accumulates_within_track():
    with cost.track() as t:
        cost.record(_usage())
        cost.record(_usage())

    assert t.calls == 2
    assert t.total_tokens == 3000
    assert t.reasoning_tokens == 400
    assert t.jpy > 0


def test_counts_calls_by_tier():
    with cost.track() as t:
        cost.record(_usage(tier=ModelTier.STANDARD))
        cost.record(_usage(tier=ModelTier.STANDARD))
        cost.record(_usage(tier=ModelTier.POWERFUL, model="anthropic/claude-opus-4.7"))

    assert t.calls_by_tier == {"standard": 2, "powerful": 1}
    # 「全件を powerful へ投げていない」ことを示す数字
    assert t.expensive_calls == 1


def test_tracks_are_isolated():
    with cost.track() as a:
        cost.record(_usage())
    with cost.track() as b:
        cost.record(_usage())
        cost.record(_usage())

    assert (a.calls, b.calls) == (1, 2)


# --- 並列（ここが落とし穴）------------------------------------------------


def test_records_from_worker_threads():
    """**ThreadPoolExecutor は contextvars を自動で引き継がない。**

    `map_parallel` が明示的にコピーしていないと、ワーカー内の消費が
    黙って落ちて「安く済んだ」ように見える。
    """
    with cost.track() as t:
        map_parallel(range(8), lambda _n: cost.record(_usage()))

    assert t.calls == 8


def test_concurrent_records_do_not_race():
    """同時に書かれても数を取りこぼさない。"""
    with cost.track() as t:
        map_parallel(range(50), lambda _n: cost.record(_usage(total_tokens=1)), workers=8)

    assert t.calls == 50
    assert t.total_tokens == 50


def test_worker_threads_do_not_leak_into_each_other():
    """ワーカーが別の run の tracker へ書かない。"""
    seen: list[int] = []
    lock = threading.Lock()

    def one(_n: int) -> None:
        with lock:
            seen.append(id(cost.current()))

    with cost.track() as t:
        map_parallel(range(4), one)

    assert set(seen) == {id(t)}
