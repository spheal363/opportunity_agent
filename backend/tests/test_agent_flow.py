"""MVP の基本フローを 1 本通すテスト（AGENT_STUB_MODE）。

PUT /profile -> POST /agent/runs -> GET /agent/runs/{id} -> GET /opportunities
-> GET /opportunities/{id} -> POST /interest -> POST /feedback
"""


def test_agent_run_requires_profile(client):
    res = client.post("/api/agent/runs")
    assert res.status_code == 404


def test_full_mvp_flow(client, profile_payload):
    assert client.put("/api/profile", json=profile_payload).status_code == 200

    res = client.post("/api/agent/runs")
    assert res.status_code == 200
    run_id = res.json()["data"]["run_id"]

    # TestClient は BackgroundTask をレスポンス返却後に同期実行するので、
    # ここに来た時点で run は完了している。
    res = client.get(f"/api/agent/runs/{run_id}")
    assert res.status_code == 200
    run = res.json()["data"]
    assert run["status"] == "completed"
    assert run["current_step"] == "completed"
    assert run["progress"] == 100

    logs = client.get(f"/api/agent/runs/{run_id}/logs").json()["data"]
    assert [log["step"] for log in logs][:2] == ["analyzing_profile", "planning"]

    items = client.get("/api/opportunities").json()["data"]
    assert len(items) == 3
    assert all(o["status"] == "recommended" for o in items)
    assert all(o["verified"] for o in items)
    # Serendipity 枠が TOP3 に含まれている
    assert max(o["serendipity_score"] for o in items) >= 90

    opportunity_id = items[0]["opportunity_id"]
    detail = client.get(f"/api/opportunities/{opportunity_id}").json()["data"]
    assert detail["opportunity_id"] == opportunity_id
    assert detail["reason"]

    res = client.post(f"/api/opportunities/{opportunity_id}/interest")
    assert res.status_code == 200
    assert res.json()["data"]["status"] == "interested"

    res = client.post(
        f"/api/opportunities/{opportunity_id}/feedback",
        json={"reaction": "like", "attended": True, "outcome_score": 5},
    )
    assert res.status_code == 200


def test_unknown_opportunity_returns_not_found(client):
    res = client.get("/api/opportunities/opp_does_not_exist")
    assert res.status_code == 404
