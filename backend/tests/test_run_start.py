import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from unittest.mock import Mock

import pytest

from config import Settings
from db.session import SessionLocal
from models import AgentRun
from schemas.agent import AgentRunStatus, AgentRunTrigger
from services import agent_service, auto_explore
from tests.auto_explore_seed import USER, add_dislike, add_opp, add_profile, add_run

PAGE = {"X-Requested-With": "opportunity-agent"}


@pytest.fixture
def seeded():
    with SessionLocal() as db:
        add_profile(db)
        for oid in ("a", "b", "c"):
            add_opp(db, oid)
        add_run(
            db,
            "previous",
            created=datetime.now(UTC) - timedelta(hours=25),
            selected=["a", "b", "c"],
        )
        add_dislike(db, "a")
        add_dislike(db, "b")


@pytest.mark.parametrize(
    "first_kind,second_kind",
    [
        ("scheduled", "manual"),
        ("manual", "scheduled"),
        ("feedback", "manual"),
        ("manual", "feedback"),
        ("manual", "manual"),
    ],
)
def test_start_is_serialized_across_manual_and_automatic_paths(
    seeded, monkeypatch, first_kind, second_kind
):
    """最初の作成が終わる前に次の開始要求を送り、実行される run が1本だけか確認。"""
    settings = Settings(_env_file=None, auto_explore_schedule=True, auto_explore_on_feedback=True)
    monkeypatch.setattr(auto_explore, "get_settings", lambda: settings)
    monkeypatch.setattr(agent_service, "get_settings", lambda: settings)
    first_creating = threading.Event()
    second_waiting = threading.Event()
    release = threading.Event()
    original_create = agent_service.create_run

    class ObservedLock:
        def __init__(self):
            self.lock = threading.Lock()

        def __enter__(self):
            if first_creating.is_set():
                second_waiting.set()
            self.lock.acquire()

        def __exit__(self, *_):
            self.lock.release()

    lock = ObservedLock()
    monkeypatch.setattr(agent_service, "start_lock", lock)
    monkeypatch.setattr(auto_explore, "_start_lock", lock)

    def paused_create(*args, **kwargs):
        first_creating.set()
        assert release.wait(5)
        return original_create(*args, **kwargs)

    monkeypatch.setattr(agent_service, "create_run", paused_create)

    def start(kind):
        with SessionLocal() as db:
            if kind == "manual":
                run, created = agent_service.start_manual_run(db, USER)
                return run.run_id if created else None
            if kind == "feedback":
                return auto_explore.start_after_feedback(db, USER, "dislike")
            return auto_explore.start_on_tick(db, USER)

    with ThreadPoolExecutor(max_workers=2) as pool:
        first = pool.submit(start, first_kind)
        try:
            assert first_creating.wait(5)
            second = pool.submit(start, second_kind)
            assert second_waiting.wait(5)
        finally:
            release.set()
        assert first.result(timeout=5) is not None
        assert second.result(timeout=5) is None
    with SessionLocal() as db:
        assert db.query(AgentRun).filter(AgentRun.status.in_(["queued", "running"])).count() == 1


@pytest.mark.parametrize("status", [AgentRunStatus.QUEUED, AgentRunStatus.RUNNING])
def test_manual_request_reuses_automatic_run_without_scheduling_work(
    client, seeded, monkeypatch, status
):
    with SessionLocal() as db:
        add_run(
            db,
            "already_running",
            created=datetime.now(UTC),
            status=status,
            trigger=AgentRunTrigger.SCHEDULED,
        )
    execute = Mock()
    monkeypatch.setattr("api.routes.agent.run_agent", execute)
    response = client.post("/api/agent/runs", headers=PAGE)
    assert response.status_code == 200
    assert response.json()["data"] == {"run_id": "already_running", "status": status}
    execute.assert_not_called()


def test_two_manual_requests_schedule_only_one_task(client, seeded, monkeypatch):
    execute = Mock()
    monkeypatch.setattr("api.routes.agent.run_agent", execute)
    first = client.post("/api/agent/runs", headers=PAGE).json()["data"]
    second = client.post("/api/agent/runs", headers=PAGE).json()["data"]
    assert first == second
    execute.assert_called_once_with(first["run_id"], USER)


def test_manual_start_recovers_abandoned_run_and_ignores_other_user(seeded):
    with SessionLocal() as db:
        add_run(
            db,
            "stuck",
            created=datetime.now(UTC) - timedelta(hours=2),
            status=AgentRunStatus.RUNNING,
        )
        add_run(
            db, "other", created=datetime.now(UTC), status=AgentRunStatus.RUNNING, user_id="other"
        )
        result, created = agent_service.start_manual_run(db, USER)
        assert created
        assert result.run_id not in {"stuck", "other"}
        db.expire_all()
        assert db.get(AgentRun, "stuck").status == AgentRunStatus.FAILED
        assert db.get(AgentRun, "other").status == AgentRunStatus.RUNNING
