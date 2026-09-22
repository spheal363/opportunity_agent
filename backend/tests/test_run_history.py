from datetime import UTC, datetime, timedelta

import pytest

from db.session import SessionLocal
from models import AgentRun, Opportunity
from schemas.agent import AgentRunStatus, AgentRunTrigger
from tests.auto_explore_seed import USER, add_run


@pytest.fixture
def db():
    with SessionLocal() as session:
        yield session


def test_empty_history(client):
    response = client.get("/api/agent/runs")
    assert response.status_code == 200
    assert response.json()["data"] == {"items": [], "next_cursor": None}


def test_history_contains_all_statuses_and_triggers_but_only_own_runs(client, db):
    created = datetime(2026, 9, 22, 3, 0)
    for i, (status, trigger) in enumerate(zip(AgentRunStatus, AgentRunTrigger, strict=True)):
        add_run(
            db, f"run_{i}", created=created + timedelta(minutes=i), status=status, trigger=trigger
        )
    add_run(db, "run_other", created=created + timedelta(days=1), user_id="other")

    response = client.get("/api/agent/runs").json()["data"]
    assert [r["run_id"] for r in response["items"]] == ["run_3", "run_2", "run_1", "run_0"]
    assert {r["status"] for r in response["items"]} == {s.value for s in AgentRunStatus}
    assert {r["trigger"] for r in response["items"]} == {s.value for s in AgentRunTrigger}
    stamp = datetime.fromisoformat(response["items"][0]["created_at"])
    assert stamp.utcoffset() == timedelta(0)
    assert stamp.hour == 3


def test_history_distinguishes_old_record_from_zero_results(client, db):
    created = datetime.now(UTC).replace(tzinfo=None)
    for name, selected in (("old", None), ("zero", []), ("three", ["a", "b", "c"])):
        add_run(db, name, created=created, selected=selected)
    items = client.get("/api/agent/runs").json()["data"]["items"]
    assert {r["run_id"]: r["selected_count"] for r in items} == {"old": None, "zero": 0, "three": 3}


def test_cursor_pagination_handles_same_timestamp_and_new_insertions(client, db):
    created = datetime.now(UTC).replace(tzinfo=None)
    for suffix in "abcd":
        add_run(db, f"run_{suffix}", created=created)
    first = client.get("/api/agent/runs?limit=2").json()["data"]
    assert [r["run_id"] for r in first["items"]] == ["run_d", "run_c"]
    assert first["next_cursor"] == "run_c"
    add_run(db, "run_new", created=created + timedelta(seconds=1))
    second = client.get(
        "/api/agent/runs", params={"limit": 2, "before": first["next_cursor"]}
    ).json()["data"]
    assert [r["run_id"] for r in second["items"]] == ["run_b", "run_a"]
    assert second["next_cursor"] is None


@pytest.mark.parametrize("cursor", ["run_other", "nonexistent"])
def test_cursor_does_not_expose_other_users_history(client, db, cursor):
    add_run(db, "run_other", created=datetime.now(UTC), user_id="other")
    assert client.get("/api/agent/runs", params={"before": cursor}).status_code == 404


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_history_rejects_invalid_page_sizes(client, limit):
    assert client.get("/api/agent/runs", params={"limit": limit}).status_code == 422


def test_result_excludes_foreign_candidates_even_if_selected_ids_are_inconsistent(client, db):
    db.add(Opportunity(opportunity_id="foreign", user_id="other", title="Private", type="event"))
    db.add(Opportunity(opportunity_id="mine", user_id=USER, title="Mine", type="event"))
    db.add(
        AgentRun(
            run_id="run_mine", user_id=USER, status="completed", selected_ids=["foreign", "mine"]
        )
    )
    db.commit()
    response = client.get("/api/agent/runs/run_mine/result")
    assert response.status_code == 200
    assert [o["opportunity_id"] for o in response.json()["data"]["selected"]] == ["mine"]


def test_result_service_itself_checks_ownership(db):
    from services import agent_service

    add_run(db, "run_other", created=datetime.now(UTC), user_id="other", selected=[])
    assert agent_service.get_result(db, "run_other", USER) is None
