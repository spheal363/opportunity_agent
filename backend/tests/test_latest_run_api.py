"""GET /api/agent/runs/latest（#86）。

Agent が自分で始めた探索を、画面が見つけるための入口。
"""

import pytest

from db.session import SessionLocal
from models import AgentRun
from schemas.agent import AgentRunStatus, AgentRunTrigger
from tests.auto_explore_seed import add_run, ago

PAGE = {"X-Requested-With": "opportunity-agent"}


@pytest.fixture
def db():
    s = SessionLocal()
    yield s
    s.close()


def test_no_run_yet_is_null_not_404(client):
    """まだ探索していないのは正常な状態。エラーにしない。"""
    res = client.get("/api/agent/runs/latest")

    assert res.status_code == 200
    assert res.json() == {"success": True, "data": None}


def test_returns_the_newest_run_with_its_trigger(client, db):
    add_run(db, "run_old", created=ago(hours=5))
    add_run(
        db,
        "run_new",
        created=ago(minutes=3),
        status=AgentRunStatus.RUNNING,
        trigger=AgentRunTrigger.SCHEDULED,
    )
    row = db.get(AgentRun, "run_new")
    row.trigger_reason = "前回の探索から25時間たったため、新着を探します"
    db.commit()

    data = client.get("/api/agent/runs/latest").json()["data"]

    assert data["run_id"] == "run_new"
    assert data["status"] == "running"
    assert data["trigger"] == "scheduled"
    assert data["trigger_reason"] == "前回の探索から25時間たったため、新着を探します"


def test_does_not_return_someone_elses_run(client, db):
    """他人の run は存在しないのと同じに扱う（#69）。"""
    add_run(db, "run_mine", created=ago(hours=5))
    add_run(db, "run_theirs", created=ago(minutes=1), user_id="user_999")

    data = client.get("/api/agent/runs/latest").json()["data"]
    assert data["run_id"] == "run_mine"


def test_only_someone_elses_run_is_null(client, db):
    add_run(db, "run_theirs", created=ago(minutes=1), user_id="user_999")

    assert client.get("/api/agent/runs/latest").json()["data"] is None


def test_latest_is_not_taken_as_a_run_id(client, db):
    """`/runs/{run_id}` と衝突しない。個別の取得もそのまま動く。"""
    add_run(db, "run_a", created=ago(minutes=1))

    assert client.get("/api/agent/runs/latest").json()["data"]["run_id"] == "run_a"
    assert client.get("/api/agent/runs/run_a").json()["data"]["run_id"] == "run_a"


def test_manual_run_started_from_the_screen_comes_back(client, profile_payload):
    client.put("/api/profile", json=profile_payload, headers=PAGE)
    run_id = client.post("/api/agent/runs", headers=PAGE).json()["data"]["run_id"]

    data = client.get("/api/agent/runs/latest").json()["data"]

    assert data["run_id"] == run_id
    assert data["trigger"] == "manual"
    assert data["trigger_reason"] is None


def test_the_newer_of_two_runs_in_the_same_second_wins(client, profile_payload):
    """作成時刻はマイクロ秒まで持つ。続けて始めても前後を取り違えない。"""
    client.put("/api/profile", json=profile_payload, headers=PAGE)
    client.post("/api/agent/runs", headers=PAGE)
    second = client.post("/api/agent/runs", headers=PAGE).json()["data"]["run_id"]

    assert client.get("/api/agent/runs/latest").json()["data"]["run_id"] == second
