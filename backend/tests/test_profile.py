# 画面（frontend/src/api/client.ts）が付けるヘッダー。状態を変える API に必須（#80）
PAGE = {"X-Requested-With": "opportunity-agent"}


def test_profile_missing_returns_not_found(client):
    res = client.get("/api/profile")
    assert res.status_code == 404
    assert res.json()["error"]["code"] == "NOT_FOUND"


def test_profile_upsert_and_get(client, profile_payload):
    res = client.put("/api/profile", json=profile_payload, headers=PAGE)
    assert res.status_code == 200
    assert res.json()["data"]["user_id"]

    res = client.get("/api/profile")
    assert res.status_code == 200
    data = res.json()["data"]
    assert data["name"] == "Naoya"
    assert data["skills"] == profile_payload["skills"]


def test_profile_validation_error(client):
    res = client.put("/api/profile", json={"location": "Tokyo"}, headers=PAGE)  # name がない
    assert res.status_code == 422
    assert res.json()["error"]["code"] == "VALIDATION_ERROR"
