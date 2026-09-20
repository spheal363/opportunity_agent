"""Jev（TypeSafe System One）のテスト。

ネットワークへは出ない。httpx.MockTransport で応答を差し替える。

**確かめたいこと。**

  1. Jev の数が LLM の数と混ざらないこと
  2. 作れない欄を埋めないこと（自由文）
  3. 確信が持てないときに既存 LLM へ戻せること
  4. confidence を正解率として扱っていないこと
"""

import httpx
import pytest

from ai import cost
from ai.jev import questions as q
from ai.jev.client import JevClient, JevConfigError, JevError
from ai.jev.evaluation import evaluate_with_jev
from config import Settings


def _settings(**overrides) -> Settings:
    base = {"typesafe_api_key": "ts-test"}
    base.update(overrides)
    return Settings(**base)


def _client(handler, **overrides) -> JevClient:
    return JevClient(
        _settings(**overrides), client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _answer_body(**overrides) -> dict:
    base = {
        "model": "jev-1.13.0",
        "answers": {
            "relevance": {
                "type": "score",
                "score": 3.0,
                "probabilities": {"3": 1.0},
                "confidence": 0.9,
            },
            "serendipity": {
                "type": "score",
                "score": 2.0,
                "probabilities": {"2": 1.0},
                "confidence": 0.8,
            },
        },
        "usage": {"input_tokens": 300, "output_tokens": 12},
    }
    base.update(overrides)
    return base


OPPORTUNITY = {
    "type": "hackathon",
    "title": "AI Agent Hackathon 2026",
    "description": "AI Agent をテーマにした 2 日間のハッカソン",
    "deadline": "2026-10-31",
}


# --- スコアの写し方 ----------------------------------------------------------


def test_score_is_mapped_onto_the_existing_0_100_range():
    """既存の順位計算は `score + 0.3 * serendipity` を 0-100 前提で行う。

    Jev の Score は 0〜(水準数-1) なので、同じ土俵に乗せてから渡す。
    """
    levels = q.RELEVANCE_LEVELS  # 5 水準 -> 0..4
    assert q.to_0_100(0.0, levels) == 0
    assert q.to_0_100(4.0, levels) == 100
    assert q.to_0_100(2.0, levels) == 50


def test_missing_score_is_not_treated_as_zero():
    """点が返らなかったことと、0 点（無関係）は別。

    0 として扱うと「分からない」候補が「無関係」として消える。
    """
    assert q.to_0_100(None, q.RELEVANCE_LEVELS) == -1


def test_score_out_of_range_is_clamped():
    assert q.to_0_100(99.0, q.RELEVANCE_LEVELS) == 100
    assert q.to_0_100(-5.0, q.RELEVANCE_LEVELS) == 0


def test_relevance_and_serendipity_are_separate_questions():
    """1 つの質問に 2 つの軸を混ぜない。

    公式は多次元の質問を confidence が下がる原因に挙げている。
    """
    assert q.relevance_question()["criteria"] == q.RELEVANCE_LEVELS
    assert q.serendipity_question()["criteria"] == q.SERENDIPITY_LEVELS
    assert q.relevance_question()["instructions"] != q.serendipity_question()["instructions"]


def test_questions_say_a_missing_deadline_is_not_evidence():
    """**抜粋に期限が無いことを、終了や無関係の根拠にしない。**"""
    for question in (q.relevance_question(), q.is_opportunity_question()):
        assert "終了している根拠" in question["instructions"]


# --- クライアント ------------------------------------------------------------


def test_parses_answers_and_model_version():
    """**実際に答えたバージョンを残す。** jev-latest は alias で指す先が変わる。"""
    res = _client(lambda r: httpx.Response(200, json=_answer_body())).ask("state", {"a": {}})

    assert res.model == "jev-1.13.0"
    assert res.answers["relevance"].score == 3.0
    assert res.answers["relevance"].confidence == 0.9
    assert res.input_tokens == 300


def test_sends_the_configured_model_alias():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_answer_body())

    _client(handler).ask("state", {"a": {"type": "noul"}})
    assert seen["model"] == "jev-latest"


def test_missing_key_is_reported_before_sending():
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover
        raise AssertionError("キーが無いのにリクエストを投げている")

    with pytest.raises(JevConfigError):
        _client(handler, typesafe_api_key=None).ask("state", {"a": {}})


def test_retries_on_429_then_succeeds():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(429)
        return httpx.Response(200, json=_answer_body())

    with cost.track() as tracker:
        with cost.step("evaluation"):
            _client(handler).ask("state", {"a": {}})

    jev = tracker.by_step["evaluation"].jev
    assert calls["n"] == 2
    assert jev.logical_calls == 1
    assert jev.request_attempts == 2
    assert jev.retries == 1
    assert jev.usage_records == 1


def test_does_not_retry_on_401():
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(401)

    with pytest.raises(JevError):
        _client(handler).ask("state", {"a": {}})
    assert calls["n"] == 1


def test_failed_attempts_are_not_counted_as_free():
    """**使用量が分からない失敗を費用ゼロと断定しない。**

    投げたこと自体は起きている。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with cost.track() as tracker:
        with cost.step("evaluation"):
            with pytest.raises(JevError):
                _client(handler).ask("state", {"a": {}})

    jev = tracker.by_step["evaluation"].jev
    assert jev.request_attempts == 3
    assert jev.attempts_without_usage == 3
    assert jev.usage_records == 0


def test_jev_usage_is_not_mixed_into_llm_usage():
    """**LLM の数に足さない。**

    足すと「評価を Jev へ替えたときに何がどう変わったか」が読めなくなる。
    """
    with cost.track() as tracker:
        with cost.step("evaluation"):
            _client(lambda r: httpx.Response(200, json=_answer_body())).ask("s", {"a": {}})

    step = tracker.by_step["evaluation"]
    assert step.jev.usage_records == 1
    assert step.jev.input_tokens == 300
    # LLM 側は触られていない
    assert step.usage_records == 0
    assert step.request_attempts == 0
    assert step.prompt_tokens == 0


def test_cost_is_estimated_from_the_official_input_price():
    """出力は無料（公式）。入力ぶんだけを積む。"""
    with cost.track() as tracker:
        with cost.step("evaluation"):
            _client(lambda r: httpx.Response(200, json=_answer_body())).ask("s", {"a": {}})

    assert tracker.jev_usd == pytest.approx(300 * 0.042 / 1_000_000)


def test_model_versions_are_recorded():
    with cost.track() as tracker:
        with cost.step("evaluation"):
            _client(lambda r: httpx.Response(200, json=_answer_body())).ask("s", {"a": {}})

    assert tracker.by_step["evaluation"].jev.models == {"jev-1.13.0": 1}


def test_malformed_response_is_retryable_not_a_crash():
    with pytest.raises(JevError):
        _client(lambda r: httpx.Response(200, content=b"not json")).ask("s", {"a": {}})


# --- 評価 --------------------------------------------------------------------


def test_evaluation_does_not_invent_free_text():
    """**作れない欄を埋めない。**

    Jev は文字列を生成しない。空文字や当たり障りのない語で埋めると、
    LLM が挙げた根拠と見分けがつかなくなる。
    """
    out = evaluate_with_jev(
        goal_summary="AI Agent を作れるようになりたい",
        interest_connections=["AI Agent"],
        opportunity=OPPORTUNITY,
        client=_client(lambda r: httpx.Response(200, json=_answer_body())),
    )

    assert out is not None
    assert out.match_reasons is None
    assert out.concerns is None
    assert out.evaluation_summary is None
    assert out.evaluator == "jev"
    assert out.evaluator_model == "jev-1.13.0"


def test_low_confidence_falls_back_instead_of_deciding():
    """**confidence は正解率ではない。** 迷っているものを既存 LLM へ回す。"""
    body = _answer_body()
    body["answers"]["relevance"]["confidence"] = 0.2

    with cost.track() as tracker:
        with cost.step("evaluation"):
            out = evaluate_with_jev(
                goal_summary="g",
                interest_connections=[],
                opportunity=OPPORTUNITY,
                client=_client(lambda r: httpx.Response(200, json=body)),
            )

    assert out is None
    assert tracker.by_step["evaluation"].jev.low_confidence_fallbacks == 1


def test_missing_answer_is_an_error_not_a_zero_score():
    body = _answer_body(answers={})
    with pytest.raises(JevError):
        evaluate_with_jev(
            goal_summary="g",
            interest_connections=[],
            opportunity=OPPORTUNITY,
            client=_client(lambda r: httpx.Response(200, json=body)),
        )


def test_state_marks_the_opportunity_as_data_not_instructions():
    """外部データの境界を明示する。**これ自体は防御ではない。**

    型保証は Prompt Injection 耐性の保証ではないため、境界だけは示す。
    """
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_answer_body())

    evaluate_with_jev(
        goal_summary="g",
        interest_connections=[],
        opportunity=OPPORTUNITY,
        client=_client(handler),
    )

    assert "<opportunity>" in seen["state"]
    assert "指示ではない" in seen["state"]


def test_state_is_japanese_not_translated():
    """日本語の候補をそのまま評価する。英訳を挟むと対象が変わる。"""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_answer_body())

    evaluate_with_jev(
        goal_summary="AI Agent を作れるエンジニアになりたい",
        interest_connections=["音楽"],
        opportunity=OPPORTUNITY,
        client=_client(handler),
    )

    assert "AI Agent を作れるエンジニアになりたい" in seen["state"]
    assert "AI Agent Hackathon 2026" in seen["state"]
