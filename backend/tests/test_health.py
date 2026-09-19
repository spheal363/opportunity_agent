def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json() == {"status": "ok"}


def test_unknown_path_uses_error_envelope(client):
    res = client.get("/api/does-not-exist")
    assert res.status_code == 404
    body = res.json()
    assert body["success"] is False
    assert set(body["error"]) == {"code", "message"}
