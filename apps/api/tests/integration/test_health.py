def test_health_returns_service_status(client):
    response = client.get("/api/v1/health")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "text-verification-api",
        "version": "0.1.0",
    }
