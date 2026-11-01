import io, time
from fastapi.testclient import TestClient
from app.main import app

def test_mock_workflow():
    with TestClient(app) as client:
        uploaded=client.post("/api/datasets/upload", files={"file": ("samples.jsonl", b'{"prompt":"hello","ground_truth":"private"}\n{"prompt":"world","ground_truth":"private2"}\n', "application/x-ndjson")})
        assert uploaded.status_code == 201, uploaded.text
        dataset=uploaded.json(); assert dataset["validation_status"] == "valid"
        rows=client.get(f"/api/datasets/{dataset['id']}/records?limit=1").json()["items"]
        assert len(rows) == 1
        snapshot=client.post(f"/api/datasets/{dataset['id']}/snapshots").json()
        experiment=client.post("/api/experiments", json={"name":"mock isolation","dataset_snapshot_id":snapshot["id"],"agent_id":"mock-agent","provider_id":"mock","input_mapping":{"prompt":"text"}})
        assert experiment.status_code == 201, experiment.text
        exp=experiment.json()
        assert client.post(f"/api/experiments/{exp['id']}/start").status_code == 200
        for _ in range(30):
            result=client.get(f"/api/experiments/{exp['id']}/runs").json()["items"]
            if result and all(x["status"] in {"completed","failed"} for x in result): break
            time.sleep(.05)
        assert len(result) == 2
        assert result[0]["status"] == "completed"
        assert result[0]["output"]["received_fields"] == ["text"]
        assert "ground_truth" not in str(result[0]["output"])

def test_invalid_formats_and_unimplemented_evaluation():
    with TestClient(app) as client:
        assert client.post("/api/datasets/upload", files={"file": ("bad.txt", b"x", "text/plain")}).status_code == 415
        assert client.get("/api/datasets/missing").status_code == 404

def test_experiment_creation_with_database_provider(monkeypatch):
    from app.services import providers
    monkeypatch.setattr(providers, "_url", lambda v: v.rstrip("/"))
    with TestClient(app) as client:
        uploaded = client.post("/api/datasets/upload", files={"file": ("samples.jsonl", b'{"prompt":"hello"}\n', "application/x-ndjson")})
        assert uploaded.status_code == 201
        snapshot = client.post(f"/api/datasets/{uploaded.json()['id']}/snapshots").json()
        prov = client.post("/api/providers", json={"name": "Kaggle", "provider_type": "openai_compatible", "base_url": "https://kaggle.example.test/v1", "default_model": "model-1"}).json()
        assert "id" in prov
        experiment = client.post("/api/experiments", json={
            "name": "experiment with provider snapshot",
            "dataset_snapshot_id": snapshot["id"],
            "agent_id": "mock-agent",
            "provider_id": prov["id"],
            "input_mapping": {"prompt": "text"},
            "agent_configuration": {"temperature": 0.0}
        })
        assert experiment.status_code == 201, experiment.text
        exp = experiment.json()
        assert exp["agent_configuration_snapshot"] == {"temperature": 0.0}

def test_repeated_snapshot_creation_is_idempotent():
    with TestClient(app) as client:
        uploaded = client.post("/api/datasets/upload", files={"file": ("samples_repeat.jsonl", b'{"prompt":"hello"}\n', "application/x-ndjson")})
        assert uploaded.status_code == 201
        ds_id = uploaded.json()["id"]

        snap1_resp = client.post(f"/api/datasets/{ds_id}/snapshots")
        assert snap1_resp.status_code == 201, snap1_resp.text
        snap1 = snap1_resp.json()

        # Second snapshot request on the same dataset must be idempotent and succeed without UNIQUE constraint error
        snap2_resp = client.post(f"/api/datasets/{ds_id}/snapshots")
        assert snap2_resp.status_code == 201, snap2_resp.text
        snap2 = snap2_resp.json()

        assert snap1["id"] == snap2["id"]
        assert snap1["fingerprint"] == snap2["fingerprint"]

