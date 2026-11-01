from fastapi.testclient import TestClient
from cryptography.fernet import Fernet
from app.main import app
from app.services import providers

def provider_body(**extra):
    return {"name":"Kaggle LLM", "provider_type":"openai_compatible", "base_url":"https://kaggle.example.test/v1", "default_model":"my-model", **extra}

def test_api_prefix_has_no_v1_route():
    paths=set(app.openapi()["paths"])
    assert "/api/providers" in paths
    legacy_prefix = "/api/" + "v1"
    assert not any(path.startswith(legacy_prefix) or "/api/api" in path for path in paths)

def test_provider_crud_and_secret_redaction(monkeypatch):
    monkeypatch.setattr(providers, "_fernet", lambda: Fernet(Fernet.generate_key()))
    monkeypatch.setattr(providers, "_url", lambda value: value.rstrip("/"))
    with TestClient(app) as client:
        created=client.post("/api/providers",json=provider_body(api_key="not-returned")).json()
        assert created["api_key_configured"] is True and "not-returned" not in str(created)
        item=client.patch(f"/api/providers/{created['id']}",json={"name":"Renamed"}).json()
        assert item["name"] == "Renamed" and item["api_key_configured"]
        assert client.patch(f"/api/providers/{created['id']}",json={"clear_api_key":True}).json()["api_key_configured"] is False
        assert client.delete(f"/api/providers/{created['id']}").status_code == 204

def test_openai_compatible_discovery_test_and_generate(monkeypatch):
    monkeypatch.setattr(providers, "_url", lambda value: value.rstrip("/"))
    calls=[]
    def fake_request(item, suffix, method="GET", payload=None):
        calls.append((item.base_url,suffix,method,payload))
        if suffix == "/models": return {"data":[{"id":"chosen"}]}
        return {"choices":[{"message":{"role":"assistant","content":"OK"}}]}
    monkeypatch.setattr(providers, "_request", fake_request)
    with TestClient(app) as client:
        item=client.post("/api/providers",json=provider_body(default_model="chosen")).json()
        assert client.get(f"/api/providers/{item['id']}/models").json()["items"] == ["chosen"]
        assert client.post(f"/api/providers/{item['id']}/test-connection").json()["ok"]
        from app.database.session import SessionLocal
        db=SessionLocal()
        try: assert providers.generate(db,item["id"],[{"role":"user","content":"hello"}])["choices"]
        finally: db.close()
    assert all(call[0] == "https://kaggle.example.test/v1" for call in calls)

def test_provider_timeout_configuration(monkeypatch):
    monkeypatch.setattr(providers, "_url", lambda value: value.rstrip("/"))
    with TestClient(app) as client:
        # 1. Verify default timeout is 30 seconds when omitted
        default_item = client.post("/api/providers", json=provider_body()).json()
        assert default_item["timeout_seconds"] == 30.0
        client.delete(f"/api/providers/{default_item['id']}")

        # 2. Verify accepted timeout values (30, 60, 90, 120, 180, 300)
        for timeout in [30, 60, 90, 120, 180, 300]:
            created = client.post("/api/providers", json=provider_body(timeout_seconds=timeout)).json()
            assert created.get("timeout_seconds") == float(timeout)
            
            # Verify update (PATCH) also accepts these values
            patched = client.patch(f"/api/providers/{created['id']}", json={"timeout_seconds": timeout + 5}).json()
            assert patched.get("timeout_seconds") == float(timeout + 5)
            
            client.delete(f"/api/providers/{created['id']}")

        # 3. Verify invalid timeouts (zero, negative, non-numeric) are rejected
        for bad_timeout in [0, -1, -60, "not-a-number"]:
            res = client.post("/api/providers", json=provider_body(timeout_seconds=bad_timeout))
            assert res.status_code == 422, f"Expected 422 for timeout={bad_timeout}, got {res.status_code}"

        # 4. Verify PATCH rejects invalid timeouts
        item = client.post("/api/providers", json=provider_body(timeout_seconds=60)).json()
        for bad_timeout in [0, -15, "invalid"]:
            patch_res = client.patch(f"/api/providers/{item['id']}", json={"timeout_seconds": bad_timeout})
            assert patch_res.status_code == 422, f"Expected 422 for PATCH timeout={bad_timeout}, got {patch_res.status_code}"
        client.delete(f"/api/providers/{item['id']}")

def test_app_encryption_key_live_storage_and_redaction(monkeypatch):
    monkeypatch.setattr(providers, "_url", lambda value: value.rstrip("/"))
    from app.core.config import settings
    assert settings.app_encryption_key is not None
    assert len(settings.app_encryption_key) == 44

    with TestClient(app) as client:
        # Register a provider using live encryption settings (no _fernet monkeypatch)
        created = client.post("/api/providers", json=provider_body(
            id="test-fernet-live",
            name="Live Fernet Provider",
            base_url="https://openrouter.ai/api/v1",
            api_key="sk-live-test-dummy-key"
        )).json()

        assert created["id"] == "test-fernet-live"
        assert created["api_key_configured"] is True
        assert "api_key" not in created
        assert "sk-live-test-dummy-key" not in str(created)

        # Inspect database record
        from app.database.session import SessionLocal
        from app.models.entities import ProviderConfiguration
        db = SessionLocal()
        try:
            stored = db.get(ProviderConfiguration, "test-fernet-live")
            assert stored is not None
            assert stored.encrypted_api_key is not None
            assert stored.encrypted_api_key.startswith("gAAAAA")
            assert stored.encrypted_api_key != "sk-live-test-dummy-key"
            assert providers.decrypt_api_key(stored.encrypted_api_key) == "sk-live-test-dummy-key"
        finally:
            db.close()

        # Clean up
        assert client.delete("/api/providers/test-fernet-live").status_code == 204


