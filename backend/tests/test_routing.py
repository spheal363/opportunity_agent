"""工程ごとのモデル振り分け（#26-b）。ネットワークへは出ない。

見るもの:

  - 表そのものの制約（外部由来に CHEAP を使わない / POWERFUL を常用しない）
  - `generate_structured` が工程から tier を決めていること
  - 元へ戻す経路（`LLM_ROUTING=standard`）
  - Fallback と、失敗したときの課金記録が振り分けを入れても壊れていないこと
"""

import json

import httpx
import pytest
from pydantic import BaseModel, Field

from ai import cost, routing
from ai.llm import LLMValidationError, generate_structured
from ai.orcarouter import LLMRequestError, ModelTier, OrcaRouterClient
from ai.routing import Route, RoutingError, Step, route_for
from config import Settings


class Sample(BaseModel):
    goal_summary: str
    score: int = Field(ge=0, le=100)


def _settings(**overrides) -> Settings:
    base = {
        "orcarouter_api_key": "sk-orca-test",
        "orcarouter_base_url": "https://api.example.com/v1",
        "llm_model_cheap": "cheap/model",
        "llm_model_standard": "standard/model",
        "llm_model_powerful": "powerful/model",
    }
    base.update(overrides)
    return Settings(**base)


def _client_returning(*payloads: object) -> tuple[OrcaRouterClient, list]:
    sent: list = []
    seq = list(payloads)
    last = payloads[-1] if payloads else "{}"

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(json.loads(request.content))
        item = seq.pop(0) if seq else last
        if isinstance(item, int):
            return httpx.Response(item, json={"error": "nope"})
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": item}}],
                "usage": {
                    "prompt_tokens": 1,
                    "completion_tokens": 2,
                    "total_tokens": 3,
                    "completion_tokens_details": {"reasoning_tokens": 0},
                },
            },
        )

    return (
        OrcaRouterClient(_settings(), client=httpx.Client(transport=httpx.MockTransport(handler))),
        sent,
    )


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr("ai.llm.time.sleep", lambda _: None)


OK = '{"goal_summary": "AI", "score": 1}'


# --- 表そのもの -----------------------------------------------------------


def test_every_step_has_a_route():
    """欠けていると既定へ黙って落ちる。**足したら表にも足す。**"""
    assert {s for s, _ in routing.table()} == set(Step)


@pytest.mark.parametrize("step", list(Step))
def test_untrusted_steps_are_never_cheap(step):
    """外部由来のデータを読む工程に CHEAP を使わない。

    cheap は Prompt Injection に 1/2 で突破される実測がある（`ai/llm.py`）。
    """
    route = route_for(step)
    if route.reads_untrusted:
        assert route.tier is not ModelTier.CHEAP


def test_the_steps_that_read_external_data_are_marked():
    """**印の付け忘れを検出する。** 印が漏れると CHEAP 禁止が効かない。

    外部本文そのものを読むのは抽出と検証。評価と推薦理由は、抽出結果という
    **外部由来のデータ**を読む。要約を経ても trusted には格上げしない。
    """
    reads = {s for s, r in routing.table() if r.reads_untrusted}
    assert reads == {Step.EXTRACTION, Step.EVALUATION, Step.RECOMMENDATION, Step.VERIFICATION}


def test_no_step_uses_powerful_by_default():
    """powerful は 1 呼び出し 4.5 秒。上がるのは Fallback のときだけ。"""
    assert all(r.tier is not ModelTier.POWERFUL for _, r in routing.table())


def test_every_route_explains_itself():
    """理由の無い振り分けを置かない。Log と表にそのまま出る。"""
    assert all(r.reason.strip() for _, r in routing.table())


def test_a_broken_table_is_rejected():
    """**表だけ書き換えて制約を破れないようにする。**"""
    broken = {
        s: (
            Route(tier=ModelTier.CHEAP, reads_untrusted=True, reason="x")
            if s is Step.EXTRACTION
            else r
        )
        for s, r in routing.table()
    }
    with pytest.raises(RoutingError, match="CHEAP"):
        routing._check_table(broken)


def test_a_table_with_a_missing_step_is_rejected():
    routes = dict(routing.table())
    del routes[Step.VERIFICATION]
    with pytest.raises(RoutingError, match="振り分けの無い工程"):
        routing._check_table(routes)


def test_powerful_in_the_table_is_rejected():
    routes = dict(routing.table())
    routes[Step.SEARCH_PLAN] = Route(tier=ModelTier.POWERFUL, reads_untrusted=False, reason="x")
    with pytest.raises(RoutingError, match="POWERFUL"):
        routing._check_table(routes)


# --- 解決 -----------------------------------------------------------------


def test_the_step_decides_the_model():
    """工程を渡せば、表の tier でリクエストが出る。

    表を書き換えたときに**実際のリクエストまで追随するか**を見る。
    期待値を定数で書くと、表を変えた瞬間にここが嘘になる。
    """
    c, sent = _client_returning(OK)
    generate_structured(schema=Sample, system="s", user="u", step=Step.SEARCH_PLAN, client=c)

    expected = {
        ModelTier.CHEAP: "cheap/model",
        ModelTier.STANDARD: "standard/model",
    }[route_for(Step.SEARCH_PLAN).tier]
    assert sent[0]["model"] == expected


def test_an_explicit_tier_wins_over_the_step():
    """比較実験は tier を明示する。表に引きずられない。"""
    c, sent = _client_returning(OK)
    generate_structured(
        schema=Sample,
        system="s",
        user="u",
        step=Step.EXTRACTION,
        tier=ModelTier.CHEAP,
        client=c,
    )
    assert sent[0]["model"] == "cheap/model"


def test_without_a_step_it_stays_on_standard():
    """工程を渡さない呼び出しを、黙って安いほうへ倒さない。"""
    c, sent = _client_returning(OK)
    generate_structured(schema=Sample, system="s", user="u", client=c)
    assert sent[0]["model"] == "standard/model"


def test_llm_routing_standard_puts_everything_back(monkeypatch):
    """**元へ戻す経路。** 環境変数 1 つで振り分け前と同じになる。"""
    monkeypatch.setattr(routing, "get_settings", lambda: _settings(llm_routing="standard"))
    for step in Step:
        assert route_for(step).tier is ModelTier.STANDARD


def test_llm_routing_standard_reaches_the_request(monkeypatch):
    monkeypatch.setattr(routing, "get_settings", lambda: _settings(llm_routing="standard"))
    c, sent = _client_returning(OK)
    generate_structured(schema=Sample, system="s", user="u", step=Step.SEARCH_PLAN, client=c)
    assert sent[0]["model"] == "standard/model"


# --- Fallback と課金記録 ---------------------------------------------------


def test_fallback_still_goes_upward_from_a_routed_step():
    """振り分けを入れても、落とす先は上のまま。"""
    c, sent = _client_returning(404, 404, 404, 404)
    with pytest.raises(LLMRequestError):
        generate_structured(
            schema=Sample, system="s", user="u", step=Step.SEARCH_PLAN, client=c, max_attempts=1
        )

    models = [s["model"] for s in sent]
    assert "cheap/model" not in models[1:]
    assert models[-1] == "powerful/model"


def test_a_failed_call_still_records_what_it_spent():
    """**失敗しても課金は起きている。** ゼロとして扱わない。"""
    c, _ = _client_returning('{"bad": 1}', '{"bad": 2}', '{"bad": 3}', '{"bad": 4}')
    with cost.track() as tracker, cost.step("search_plan"):
        with pytest.raises(LLMValidationError) as exc:
            generate_structured(
                schema=Sample,
                system="s",
                user="u",
                step=Step.SEARCH_PLAN,
                client=c,
                max_attempts=2,
            )

    assert exc.value.usages, "例外に消費量が載っていない"
    used = tracker.by_step["search_plan"]
    assert used.logical_calls == 1
    assert used.request_attempts == len(exc.value.usages)
    assert used.fallbacks == 1


# --- Log ------------------------------------------------------------------


def test_the_log_line_names_the_step_and_the_actual_model(caplog):
    """#54 で見せる行。**要求した tier と実際のモデルを別々に出す。**"""
    c, _ = _client_returning(OK)
    with caplog.at_level("INFO"):
        generate_structured(schema=Sample, system="s", user="u", step=Step.SEARCH_PLAN, client=c)

    line = next(m for m in caplog.messages if m.startswith("llm.routed"))
    assert "step=search_plan" in line
    assert f"requested={route_for(Step.SEARCH_PLAN).tier.value}" in line
    assert "model=" in line
    assert route_for(Step.SEARCH_PLAN).reason in line


def test_the_log_line_does_not_claim_zero_cost_when_it_is_unknown(caplog):
    """実費が取れない設定（既定）で 0 と書かない。無料に見える。"""
    c, _ = _client_returning(OK)
    with caplog.at_level("INFO"):
        generate_structured(schema=Sample, system="s", user="u", step=Step.EVALUATION, client=c)

    line = next(m for m in caplog.messages if m.startswith("llm.routed"))
    assert "usd=-" in line


def test_the_log_line_is_written_even_when_the_call_fails(caplog):
    c, _ = _client_returning('{"bad": 1}', '{"bad": 2}', '{"bad": 3}', '{"bad": 4}')
    with caplog.at_level("INFO"), pytest.raises(LLMValidationError):
        generate_structured(
            schema=Sample, system="s", user="u", step=Step.SEARCH_PLAN, client=c, max_attempts=2
        )

    line = next(m for m in caplog.messages if m.startswith("llm.routed"))
    assert "result=failed" in line


def test_the_log_line_does_not_carry_the_prompt(caplog):
    """プロンプト本文と Secret を Log へ出さない。"""
    c, _ = _client_returning(OK)
    with caplog.at_level("INFO"):
        generate_structured(
            schema=Sample,
            system="秘密のsystem",
            user="秘密のuser",
            step=Step.GOAL_ANALYSIS,
            client=c,
        )

    assert "秘密の" not in caplog.text
    assert "sk-orca-test" not in caplog.text


def test_the_log_counts_attempts_that_returned_no_usage(caplog):
    """**404 や timeout は usage が付かない。**

    `len(usages)` で数えると「1 回も投げていない」ことになる。実際に、
    Fallback して失敗した行が `attempts=0 fallbacks=0` と出た。
    """
    c, sent = _client_returning(404, 404)
    with caplog.at_level("INFO"), pytest.raises(LLMRequestError):
        generate_structured(
            schema=Sample, system="s", user="u", step=Step.EXTRACTION, client=c, max_attempts=1
        )

    line = next(m for m in caplog.messages if m.startswith("llm.routed"))
    assert f"attempts={len(sent)}" in line
    assert "fallbacks=1" in line
    # 使用量が取れていないので、費用は不明。0 と書かない。
    assert "usd=-" in line
