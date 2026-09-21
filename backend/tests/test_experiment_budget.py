"""実験の停止条件と記録設定（#65）。

**実費が取れない回を 0 円として素通りさせない。**

1 回目の停止条件は「実費が $0.50 を超えたら」だったが、`cost_usd` が
None の回は加算されず、**不明が続く限り止まらない設計だった。**
監査で実際に全件不明になり、費用の上限が一度も働かなかった。
"""

import pytest

from config import Settings
from scripts import _experiment


def _budget(**kwargs) -> _experiment.Budget:
    b = _experiment.Budget()
    for k, v in kwargs.items():
        setattr(b, k, v)
    return b


def test_an_unknown_cost_is_not_counted_as_zero():
    """**見積もりで代わりに積む。** 不明を無かったことにしない。"""
    b = _experiment.Budget()
    b.record_response(cost_usd=None, estimate_jpy=30.0)

    assert b.actual_usd == 0.0
    assert b.estimated_usd == pytest.approx(0.2)
    assert b.unknown_cost_responses == 1
    assert b.spent_usd == pytest.approx(0.2)


def test_an_actual_cost_is_used_when_available():
    b = _experiment.Budget()
    b.record_response(cost_usd=0.01, estimate_jpy=30.0)

    assert b.actual_usd == pytest.approx(0.01)
    assert b.estimated_usd == 0.0
    assert b.unknown_cost_responses == 0


def test_unknown_costs_can_trigger_the_spend_limit():
    """**実費が全件不明でも、費用の上限が働く。**

    ここが効かなかったのが 1 回目の設計。
    """
    b = _experiment.Budget()
    for _ in range(10):
        b.record_response(cost_usd=None, estimate_jpy=10.0)  # 合計 $0.67

    with pytest.raises(_experiment.BudgetExceededError, match="費用"):
        b.check()


def test_too_many_unknown_costs_stop_the_run():
    """**費用の上限が効かない状態そのものを止める。**"""
    b = _budget(unknown_cost_responses=_experiment.MAX_UNKNOWN_COST_RESPONSES)
    with pytest.raises(_experiment.BudgetExceededError, match="実費を取れない"):
        b.check()


def test_the_request_limit_stops_the_run():
    b = _budget(llm_requests=_experiment.MAX_LLM_REQUESTS + 1)
    with pytest.raises(_experiment.BudgetExceededError, match="LLM 実リクエスト"):
        b.check()


def test_consecutive_jev_failures_stop_the_run():
    b = _budget(jev_failures=_experiment.MAX_JEV_FAILURES)
    with pytest.raises(_experiment.BudgetExceededError, match="Jev"):
        b.check()


def test_within_the_limits_nothing_is_raised():
    _experiment.Budget().check()


def test_the_record_says_the_limit_is_not_a_hard_cap():
    """**並列で飛んでいる分は止まらない。** 記録に残す。"""
    out = _experiment.Budget().to_dict()
    assert "次を投げない" in out["note"]
    assert set(out["limits"]) == {
        "llm_requests",
        "spent_usd",
        "unknown_cost_responses",
        "jev_failures",
    }


def test_schema_failures_retries_and_fallbacks_are_recorded():
    """Schema 不通過・Retry・Fallback も記録対象。"""
    out = _budget(schema_failures=2, retries=3, fallbacks=1).to_dict()
    assert out["schema_failures"] == 2
    assert out["retries"] == 3
    assert out["fallbacks"] == 1


# --- 記録設定の漏れを実行前に見つける ---------------------------------------


def test_missing_cost_recording_is_detected():
    """**走らせたあとで気づくのでは遅い。** 取り直せない。"""
    missing = _experiment.check_recording_settings(Settings(orcarouter_include_cost=False))
    assert missing and "ORCAROUTER_INCLUDE_COST" in missing[0]


def test_nothing_missing_when_recording_is_on():
    assert _experiment.check_recording_settings(Settings(orcarouter_include_cost=True)) == []


def test_apply_sets_the_required_environment(monkeypatch):
    """**他のテストへ漏らさない。** 環境変数はプロセス全体で共有される。

    実際に漏らして、既定でヘッダを送らないことを確かめるテストが落ちた。
    """
    import os

    monkeypatch.setenv("ORCAROUTER_INCLUDE_COST", "false")
    _experiment.apply_recording_settings()
    assert os.environ["ORCAROUTER_INCLUDE_COST"] == "true"
