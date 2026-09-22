"""run の失敗理由に例外の文字列を出さない（#81）。

run の `error` は GET /api/agent/runs/{id} でそのまま画面に返る。
"""

import logging

import pytest
from fastapi.testclient import TestClient

from agent import loop
from ai.llm import LLMValidationError
from db.session import SessionLocal
from logging_config import describe_exception
from main import app
from models import DEFAULT_USER_ID, AgentRun, UserProfile
from schemas.agent import AgentRunStatus
from services import profile_service
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


def test_log_keeps_the_type_and_place_but_not_the_text(monkeypatch, run_id, caplog):
    """原因を追えるよう、例外の型と場所はサーバーのログに残す。文字列は残さない。

    例外の文字列には SQL のパラメータ（プロフィール本文）が入りうる
    （.claude/rules/security.md「プロフィール本文を Log に出さない」）。
    """
    with caplog.at_level(logging.INFO):
        _run_failing_with(monkeypatch, run_id, RuntimeError(SECRET))

    assert "agent run failed run_id=run_err" in caplog.text
    assert "type=RuntimeError" in caplog.text
    assert "boom" in caplog.text  # 例外が起きた関数
    assert "自己紹介" not in caplog.text
    assert "SELECT" not in caplog.text


def test_api_error_log_does_not_carry_the_text(monkeypatch, caplog):
    """API の想定外エラーも同じ。レスポンスにもログにも例外の文字列を出さない。"""

    def boom(*_, **__):
        raise RuntimeError(SECRET)

    monkeypatch.setattr(profile_service, "get_profile", boom)
    with caplog.at_level(logging.INFO), TestClient(app, raise_server_exceptions=False) as c:
        res = c.get("/api/profile")

    assert res.status_code == 500
    assert "自己紹介" not in res.text
    assert "unhandled error path=/api/profile type=RuntimeError" in caplog.text
    assert "自己紹介" not in caplog.text


def test_describe_exception_names_the_wrapped_cause():
    """包まれた元の例外も、型だけ添える。"""
    try:
        try:
            raise TimeoutError(SECRET)
        except TimeoutError as inner:
            raise RuntimeError(SECRET) from inner
    except RuntimeError as exc:
        text = describe_exception(exc)

    assert text.startswith("type=RuntimeError at=test_run_errors.py:")
    assert text.endswith("cause=TimeoutError")
    assert "自己紹介" not in text
