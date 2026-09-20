"""思考量の比較スクリプトのテスト。**実 API は呼ばない。**

**一番確かめたいのは「効かなかったときに気づけるか」。**

`reasoning_effort` を送って HTTP 200 が返っても、reasoning トークンが
減らなければ反映されていない。**受理されたことを効いたことと読み替えると、
比較そのものが嘘になる。**
"""

import json

import httpx
import pytest

from config import Settings
from scripts import compare_reasoning as cr


def _client(handler) -> object:
    from ai.orcarouter import OrcaRouterClient

    return OrcaRouterClient(
        Settings(
            orcarouter_api_key="k",
            orcarouter_base_url="https://example.test/v1",
            llm_model_standard="google/gemini-2.5-flash",
        ),
        client=httpx.Client(transport=httpx.MockTransport(handler)),
    )


def _body(*, reasoning: int, answer: str = '{"title":"T","type":"event"}') -> dict:
    return {
        "choices": [{"message": {"content": answer}}],
        "usage": {
            "prompt_tokens": 1000,
            "completion_tokens": reasoning + 50,
            "total_tokens": 1000 + reasoning + 50,
            "completion_tokens_details": {"reasoning_tokens": reasoning},
            "cost_usd": 0.001,
        },
    }


def _saved_call(url: str = "https://e.jp/a") -> dict:
    return {
        "step": "extraction",
        "max_tokens": 8192,
        "messages": [
            {"role": "system", "content": "s"},
            {"role": "user", "content": f"取得元 URL: {url}\n\n本文"},
        ],
    }


def test_detects_that_effort_was_ignored(capsys):
    """**送ったのに reasoning が変わらない場合を「効いていない」と言う。**"""

    def handler(request: httpx.Request) -> httpx.Response:
        # reasoning_effort を無視する provider を模す
        return httpx.Response(200, json=_body(reasoning=900))

    calls = [_saved_call()]
    efforts = [cr.CURRENT, "minimal"]
    results = cr._run_all(_client(handler), calls, efforts)
    cr._report(calls, efforts, results)

    assert "効いていない可能性が高い" in capsys.readouterr().out


def test_reports_the_reduction_when_it_works(capsys):
    """効いたときは減り幅を出す。"""

    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        reasoning = 100 if sent.get("reasoning_effort") == "minimal" else 1000
        return httpx.Response(200, json=_body(reasoning=reasoning))

    calls = [_saved_call()]
    efforts = [cr.CURRENT, "minimal"]
    results = cr._run_all(_client(handler), calls, efforts)
    cr._report(calls, efforts, results)

    out = capsys.readouterr().out
    assert "効いていない可能性が高い" not in out
    assert "-90%" in out


def test_max_tokens_is_taken_from_the_saved_call():
    """**枠は下げない。** 保存された値をそのまま使う。"""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_body(reasoning=10))

    cr._run_all(_client(handler), [_saved_call()], [cr.CURRENT])
    assert seen["max_tokens"] == 8192


def test_current_setting_sends_no_effort():
    """現行設定は**パラメータを足さない**。既定の挙動と同じものを測る。"""
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(200, json=_body(reasoning=10))

    cr._run_all(_client(handler), [_saved_call()], [cr.CURRENT])
    assert "reasoning_effort" not in seen


def test_retries_are_counted_in_the_comparison():
    """**Retry 込みで比べる。** 安くなっても再試行が増えれば意味がない。"""
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        if state["n"] == 1:
            return httpx.Response(429)
        return httpx.Response(200, json=_body(reasoning=10))

    [result] = cr._run_all(_client(handler), [_saved_call()], [cr.CURRENT])
    assert result["attempts"] == 2


def test_missing_actual_cost_is_not_counted_as_zero(capsys):
    """**実費が取れなかった回を費用ゼロとしない。** 件数を出す。"""
    body = _body(reasoning=10)
    del body["usage"]["cost_usd"]

    calls = [_saved_call()]
    results = cr._run_all(_client(lambda r: httpx.Response(200, json=body)), calls, [cr.CURRENT])
    cr._report(calls, [cr.CURRENT], results)

    assert results[0]["cost_usd"] is None
    out = capsys.readouterr().out
    assert "**実費取得不可** 1 件" in out
    assert "追加照会 1 回" in out


def test_broken_json_is_recorded_as_invalid_not_as_empty(capsys):
    """Schema を通らなかったことを、**空の抽出結果と混同しない。**"""
    body = _body(reasoning=10, answer="{壊れた")
    calls = [_saved_call()]
    results = cr._run_all(_client(lambda r: httpx.Response(200, json=body)), calls, [cr.CURRENT])

    assert "__invalid__" in results[0]["parsed"]
    cr._report(calls, [cr.CURRENT], results)
    assert "Schema 不通過 1" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("a", "b", "expected"),
    [
        ({"deadline": None}, {"deadline": "2026-10-31"}, "**null から埋まった**"),
        ({"deadline": "2026-10-31"}, {"deadline": None}, "**null になった**"),
        ({"location": "東京"}, {"location": "渋谷"}, "変化"),
    ],
)
def test_null_transitions_are_named(a, b, expected, capsys):
    """null が埋まったのか、消えたのかを分けて書く。

    どちらも「差分」で済ませると、**情報が増えたのか失われたのか**が読めない。
    """
    calls = [_saved_call()]
    results = [
        {
            "index": 1,
            "effort": cr.CURRENT,
            "attempts": 1,
            "elapsed_ms": 1,
            "parsed": a,
            "reasoning_tokens": 1,
            "answer_tokens": 1,
            "cost_usd": 0.0,
        },
        {
            "index": 1,
            "effort": "low",
            "attempts": 1,
            "elapsed_ms": 1,
            "parsed": b,
            "reasoning_tokens": 1,
            "answer_tokens": 1,
            "cost_usd": 0.0,
        },
    ]
    cr._report(calls, [cr.CURRENT, "low"], results)
    assert expected in capsys.readouterr().out


def test_plan_does_not_call_the_api(capsys):
    """計画の表示だけでは API を呼ばない。**--confirm が要る。**"""
    cr._plan([_saved_call(), _saved_call()], [cr.CURRENT, "low"], "extraction", 3)
    out = capsys.readouterr().out
    assert "4 呼び出し" in out
    assert "最大 12 リクエスト" in out


def test_plan_says_the_estimate_is_not_a_hard_maximum(capsys):
    """**平均単価からの参考額**であって、厳密な最大費用ではない。

    出力長は入力ごとに変わり、上位 tier へ落ちれば単価が 50 倍になる。
    """
    cr._plan([_saved_call()], [cr.CURRENT], "extraction", 1)
    out = capsys.readouterr().out
    assert "厳密な最大費用ではない" in out
    assert "自動 Retry なし" in out


def test_unsupported_parameter_stops_the_run(capsys):
    """**別の設定で自動的にやり直さない。**

    「この設定では駄目だった」ことを、別の設定の結果で覆い隠さないため。
    """

    def handler(request: httpx.Request) -> httpx.Response:
        import json as _json

        if _json.loads(request.content).get("reasoning_effort"):
            return httpx.Response(400, json={"error": "unsupported parameter"})
        return httpx.Response(200, json=_body(reasoning=900))

    calls = [_saved_call(), _saved_call("https://e.jp/b")]
    results = cr._run_all(_client(handler), calls, [cr.CURRENT, "low"], max_attempts=1)

    assert results[-1]["fatal"] is True
    # 2 件目には進んでいない
    assert {r["index"] for r in results} == {1}
    assert "停止する" in capsys.readouterr().out


def test_no_automatic_retry_when_attempts_is_one():
    """予備実験では失敗も結果として残す。**やり直さない。**"""
    state = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        state["n"] += 1
        return httpx.Response(429)

    [result] = cr._run_all(_client(handler), [_saved_call()], [cr.CURRENT], max_attempts=1)

    assert state["n"] == 1
    assert result["attempts"] == 1
    assert "error" in result
