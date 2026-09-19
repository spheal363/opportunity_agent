"""OrcaRouter クライアントのテスト。

ネットワークへは出ない。httpx.MockTransport で応答を差し替える。
"""

import httpx
import pytest

from ai.orcarouter import (
    EmptyResponseError,
    LLMConfigError,
    LLMRequestError,
    ModelTier,
    OrcaRouterClient,
)
from config import Settings


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


def _client(handler, **overrides) -> OrcaRouterClient:
    return OrcaRouterClient(
        _settings(**overrides), client=httpx.Client(transport=httpx.MockTransport(handler))
    )


def _ok_body(content: str = '{"ok": true}', **usage):
    body_usage = {
        "prompt_tokens": 10,
        "completion_tokens": 20,
        "total_tokens": 30,
        "completion_tokens_details": {"reasoning_tokens": 0},
    }
    body_usage.update(usage)
    return {"choices": [{"message": {"content": content}}], "usage": body_usage}


# --- 設定 ---------------------------------------------------------------


def test_model_for_each_tier():
    c = _client(lambda r: httpx.Response(200, json=_ok_body()))
    assert c.model_for(ModelTier.CHEAP) == "cheap/model"
    assert c.model_for(ModelTier.STANDARD) == "standard/model"
    assert c.model_for(ModelTier.POWERFUL) == "powerful/model"


def test_is_configured():
    assert _client(lambda r: httpx.Response(200)).is_configured is True
    assert _client(lambda r: httpx.Response(200), orcarouter_api_key=None).is_configured is False


def test_missing_api_key_raises_config_error():
    c = _client(lambda r: httpx.Response(200, json=_ok_body()), orcarouter_api_key=None)
    with pytest.raises(LLMConfigError):
        c.chat([{"role": "user", "content": "hi"}])


def test_missing_model_raises_config_error():
    c = _client(lambda r: httpx.Response(200, json=_ok_body()), llm_model_cheap=None)
    with pytest.raises(LLMConfigError):
        c.model_for(ModelTier.CHEAP)


# --- リクエストの組み立て -------------------------------------------------


def test_request_shape():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["url"] = str(request.url)
        seen["auth"] = request.headers["Authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_body())

    _client(handler).chat([{"role": "user", "content": "hi"}], tier=ModelTier.POWERFUL)

    assert seen["url"] == "https://api.example.com/v1/chat/completions"
    assert seen["auth"] == "Bearer sk-orca-test"
    assert seen["body"]["model"] == "powerful/model"
    # JSON を強制しないと ```json フェンス付きで返すモデルがある
    assert seen["body"]["response_format"] == {"type": "json_object"}
    # reasoning 系モデルが枠を使い切らないだけの余裕があること
    assert seen["body"]["max_tokens"] >= 1024


def test_json_mode_can_be_disabled():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        import json

        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=_ok_body())

    _client(handler).chat([{"role": "user", "content": "hi"}], json_mode=False)
    assert "response_format" not in seen["body"]


# --- レスポンス ----------------------------------------------------------


def test_parses_content_and_usage():
    c = _client(
        lambda r: httpx.Response(
            200,
            json=_ok_body(
                '{"a": 1}', completion_tokens_details={"reasoning_tokens": 32}, total_tokens=42
            ),
        )
    )
    res = c.chat([{"role": "user", "content": "hi"}], tier=ModelTier.STANDARD)

    assert res.content == '{"a": 1}'
    assert res.usage.model == "standard/model"
    assert res.usage.tier is ModelTier.STANDARD
    assert res.usage.reasoning_tokens == 32
    assert res.usage.total_tokens == 42
    assert res.usage.latency_ms >= 0


def test_empty_content_raises_retryable_error():
    """gemini 系が max_tokens を推論で使い切ると content が空で返る。"""
    c = _client(
        lambda r: httpx.Response(
            200, json=_ok_body("", completion_tokens_details={"reasoning_tokens": 32})
        )
    )
    with pytest.raises(EmptyResponseError) as exc:
        c.chat([{"role": "user", "content": "hi"}])
    assert exc.value.retryable is True


def test_malformed_response_raises_retryable_error():
    c = _client(lambda r: httpx.Response(200, json={"unexpected": True}))
    with pytest.raises(LLMRequestError) as exc:
        c.chat([{"role": "user", "content": "hi"}])
    assert exc.value.retryable is True


# --- エラー分類 ----------------------------------------------------------


@pytest.mark.parametrize(
    "status,retryable",
    [(429, True), (500, True), (503, True), (400, False), (401, False), (404, False)],
)
def test_status_code_classification(status, retryable):
    c = _client(lambda r: httpx.Response(status, json={"error": "nope"}))
    with pytest.raises(LLMRequestError) as exc:
        c.chat([{"role": "user", "content": "hi"}])
    assert exc.value.status_code == status
    assert exc.value.retryable is retryable


def test_timeout_is_retryable():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("too slow", request=request)

    with pytest.raises(LLMRequestError) as exc:
        _client(handler).chat([{"role": "user", "content": "hi"}])
    assert exc.value.retryable is True


def test_error_message_does_not_leak_api_key():
    """例外が Secret を含まないこと。"""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom", request=request)

    with pytest.raises(LLMRequestError) as exc:
        _client(handler).chat([{"role": "user", "content": "hi"}])
    assert "sk-orca-test" not in str(exc.value)


def test_http_client_is_created_once_without_race():
    """BackgroundTask が同時に走っても httpx.Client を二重生成しない。"""
    import threading

    created = []
    original = httpx.Client

    class Counting(original):
        def __init__(self, *a, **k):
            created.append(1)
            super().__init__(*a, **k)

    httpx.Client = Counting
    try:
        c = OrcaRouterClient(_settings())
        barrier = threading.Barrier(8)

        def touch():
            barrier.wait()
            assert c._client is not None

        threads = [threading.Thread(target=touch) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(created) == 1
        c.close()
    finally:
        httpx.Client = original


def test_empty_response_error_carries_its_usage():
    c = _client(
        lambda r: httpx.Response(
            200, json=_ok_body("", completion_tokens_details={"reasoning_tokens": 32})
        )
    )
    with pytest.raises(EmptyResponseError) as exc:
        c.chat([{"role": "user", "content": "hi"}])
    assert len(exc.value.usages) == 1
    assert exc.value.usages[0].reasoning_tokens == 32
