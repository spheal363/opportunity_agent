"""コスト記録（#26-a）。

**測定であって最適化ではない。** 品質・速度を変えたときに、コストが
どう動いたかを比べられるようにするための土台。
"""

import threading
import time

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

    assert t.usage_records == 2
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

    assert (a.usage_records, b.usage_records) == (1, 2)


# --- 並列（ここが落とし穴）------------------------------------------------


def test_records_from_worker_threads():
    """**ThreadPoolExecutor は contextvars を自動で引き継がない。**

    `map_parallel` が明示的にコピーしていないと、ワーカー内の消費が
    黙って落ちて「安く済んだ」ように見える。
    """
    with cost.track() as t:
        map_parallel(range(8), lambda _n: cost.record(_usage()))

    assert t.usage_records == 8


def test_concurrent_records_do_not_race():
    """同時に書かれても数を取りこぼさない。"""
    with cost.track() as t:
        map_parallel(
            range(50),
            lambda _n: cost.record(_usage(prompt_tokens=1, completion_tokens=0)),
            workers=8,
        )

    assert t.usage_records == 50
    # total_tokens は prompt + completion から数える（provider の total は使わない）
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


# --- 伝播対象の限定（レビュー指摘 Medium）--------------------------------


def test_only_the_cost_tracker_is_propagated():
    """**context 全体を複製しない。**

    将来ここ以外の ContextVar（認証情報やトレース ID など）を持たせたとき、
    それらまで気づかれずにワーカーへ流れないようにする。
    """
    from contextvars import ContextVar

    unrelated = ContextVar("unrelated", default=None)
    unrelated.set("auth-token-should-not-leak")

    with cost.track():
        seen = map_parallel(range(3), lambda _n: unrelated.get())

    assert seen == [None, None, None]


def test_cost_tracker_still_propagates():
    """限定しても本来の目的は果たす。"""
    with cost.track() as t:
        map_parallel(range(4), lambda _n: cost.record(_usage()))
    assert t.usage_records == 4


# --- スキーマの制約（レビュー指摘 Low）------------------------------------


@pytest.mark.parametrize("field", ["cost_jpy", "expensive_model_calls"])
def test_negative_cost_is_rejected_by_the_schema(field):
    """**コストは負にならない。** 内部のバグで巻き戻ったら早く気づけるようにする。

    同じスキーマの progress は ge=0 で縛られているのに、追加した 2 つだけ
    制約が無かった（レビュー指摘）。基準を揃える。
    """
    from pydantic import ValidationError

    from schemas.agent import AgentRunState

    base = {"run_id": "r", "status": "running"}
    AgentRunState(**base, **{field: 0})  # 0 は通る
    with pytest.raises(ValidationError):
        AgentRunState(**base, **{field: -1})


# --- 工程別の集計（#65）---------------------------------------------------


def test_records_are_attributed_to_the_step():
    with cost.track() as t:
        with cost.step("extraction"):
            cost.record(_usage())
        with cost.step("evaluation"):
            cost.record(_usage())
            cost.record(_usage())

    assert t.by_step["extraction"].usage_records == 1
    assert t.by_step["evaluation"].usage_records == 2


def test_steps_do_not_mix_across_parallel_workers():
    """**並列ワーカーでも工程が混ざらない。**"""
    with cost.track() as t:
        with cost.step("extraction"):
            map_parallel(range(6), lambda _n: cost.record(_usage()))
        with cost.step("evaluation"):
            map_parallel(range(4), lambda _n: cost.record(_usage()))

    assert t.by_step["extraction"].usage_records == 6
    assert t.by_step["evaluation"].usage_records == 4


def test_steps_do_not_mix_across_runs():
    """run を跨いで混ざらない。"""
    with cost.track() as a:
        with cost.step("extraction"):
            cost.record(_usage())
    with cost.track() as b:
        with cost.step("extraction"):
            cost.record(_usage())
            cost.record(_usage())

    assert (a.by_step["extraction"].usage_records, b.by_step["extraction"].usage_records) == (1, 2)


def test_elapsed_is_wall_clock_not_the_sum_of_parallel_calls():
    """**並列呼び出しの時間の合計ではない。** 工程に入ってから出るまで。"""
    with cost.track() as t:
        with cost.step("extraction"):
            map_parallel(range(4), lambda _n: time.sleep(0.05), workers=4)

    elapsed = t.by_step["extraction"].elapsed_ms
    # 4 並列なので合計 200ms ではなく 1 回分に近い
    assert 30 <= elapsed < 180


# --- 数の意味を混ぜない ---------------------------------------------------


def test_logical_calls_and_attempts_are_separate():
    with cost.track() as t:
        with cost.step("extraction"):
            cost.record_logical_call()
            cost.record_attempt(got_usage=True)
            cost.record(_usage())
            # 同じ論理呼び出しの中で Retry
            cost.record_retry()
            cost.record_attempt(got_usage=True)
            cost.record(_usage())

    u = t.by_step["extraction"]
    assert u.logical_calls == 1
    assert u.request_attempts == 2
    assert u.usage_records == 2
    assert u.retries == 1


def test_attempts_without_usage_are_counted():
    """**使用量が取れない失敗を費用ゼロと断定しない。**

    timeout / 接続失敗は usage が付かないが、投げたことは起きている。
    """
    with cost.track() as t:
        with cost.step("extraction"):
            cost.record_attempt(got_usage=False)
            cost.record_attempt(got_usage=True)
            cost.record(_usage())

    u = t.by_step["extraction"]
    assert u.request_attempts == 2
    assert u.attempts_without_usage == 1
    assert u.usage_records == 1


def test_search_and_extract_are_counted_separately():
    """**料金は未確認**なので回数だけ持つ。"""
    with cost.track() as t:
        cost.record_search()
        cost.record_search()
        cost.record_extract(3)

    assert (t.search_calls, t.extract_calls) == (2, 3)


def test_dropped_reasons_are_counted():
    with cost.track() as t:
        cost.record_dropped("closed_by_date", 2)
        cost.record_dropped("dismissed")
        cost.record_dropped("closed_by_date")

    assert t.dropped == {"closed_by_date": 3, "dismissed": 1}


def test_to_dict_is_serialisable():
    import json

    with cost.track() as t:
        with cost.step("extraction"):
            cost.record(_usage())
        cost.record_search()
        cost.record_final_availability(["open", "unknown", "open"])

    d = t.to_dict()
    json.dumps(d)  # DB へ JSON で入るので落ちないこと
    assert d["by_step"]["extraction"]["usage_records"] == 1
    assert d["final_availability"] == {"open": 2, "unknown": 1}
