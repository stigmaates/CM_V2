def test_healthz_returns_public_liveness_status():
    from app.main import app

    client = app.test_client()
    response = client.get("/healthz")

    assert response.status_code == 200
    data = response.get_json()
    assert data["ok"] is True
    assert data["service"] == "cyber-bonus"
    assert "version" in data
    assert "commit" in data
