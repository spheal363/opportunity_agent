"""run の失敗理由に例外の文字列を出さない（#81）。

run の `error` は GET /api/agent/runs/{id} でそのまま画面に返る。
"""

import pytest

from agent import loop
from ai.llm import LLMValidationError
from db.session import SessionLocal
from models import DEFAULT_USER_ID, AgentRun, UserProfile
from schemas.agent import AgentRunStatus
from tools.search.base import SearchError

# DB のエラーは SQL とパラメータ（プロフィール本文）を含みうる
SECRET = "SELECT * FROM user_profiles WHERE about='誰にも見せない自己紹介'"


@pytest.fixture
def run_id(profile_payload) -> str:
    db = SessionLocal()
    db.add(UserProfile(user_id=DEFAULT_USER_ID, **profile_payload))
    db.add(AgentRun(run_id="run_err", user_id=DEFAULT_USER_ID, status=AgentRunStatus.QUEUED))
    db.commit()
    db.close()
    return "run_err"


def _run_failing_with(monkeypatch, run_id: str, exc: Exception) -> AgentRun:
    def boom(*_, **__):
        raise exc

    monkeypatch.setattr(loop, "_analyze_goal", boom)
    loop.run_agent(run_id, DEFAULT_USER_ID)

    db = SessionLocal()
    try:
        return db.get(AgentRun, run_id)
    finally:
        db.close()


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (RuntimeError(SECRET), "予期しないエラーが発生しました"),
        (LLMValidationError(SECRET), "AI の呼び出しに失敗しました"),
        (SearchError(SECRET), "Web 検索に失敗しました"),
    ],
)
def test_error_is_a_fixed_message(monkeypatch, run_id, exc, expected):
    run = _run_failing_with(monkeypatch, run_id, exc)

    assert run.status == AgentRunStatus.FAILED
    assert run.error.startswith(expected)
    assert "自己紹介" not in run.error
    assert "SELECT" not in run.error


def test_api_does_not_return_the_exception_text(client, monkeypatch, run_id):
    _run_failing_with(monkeypatch, run_id, RuntimeError(SECRET))

    res = client.get(f"/api/agent/runs/{run_id}")

    assert res.status_code == 200
    assert res.json()["data"]["status"] == "failed"
    assert "自己紹介" not in res.text


def test_details_stay_in_the_server_log(monkeypatch, run_id, caplog):
    """原因を追えるよう、サーバーのログには残す（画面には出さない）。"""
    _run_failing_with(monkeypatch, run_id, RuntimeError("接続が切れました"))
    assert "agent run failed run_id=run_err" in caplog.text
