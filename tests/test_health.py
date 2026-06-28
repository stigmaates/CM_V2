def test_healthz_returns_public_liveness_status():
    from app.main import app

    client = app.test_client()
    response = client.get("/healthz")

    assert response.status_code == 200
    assert response.get_json() == {"ok": True, "service": "cyber-bonus"}
