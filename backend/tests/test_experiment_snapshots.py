from datetime import date, datetime
import pytest
from fastapi.testclient import TestClient

from app.database.session import SessionLocal
from app.main import app
from app.models.entities import Experiment
from app.services.experiments import to_json_safe
from app.services import providers as provider_service


def test_to_json_safe_helper_primitives_and_arbitrary_objects():
    # Primitives preserved exactly
    assert to_json_safe(None) is None
    assert to_json_safe(True) is True
    assert to_json_safe(False) is False
    assert to_json_safe(42) == 42
    assert type(to_json_safe(42)) is int
    assert to_json_safe(0.0) == 0.0
    assert type(to_json_safe(0.0)) is float
    assert to_json_safe("hello") == "hello"

    # Datetime and Date converted to ISO-8601 strings
    dt = datetime(2026, 10, 23, 14, 30, 15)
    d = date(2026, 10, 23)
    assert to_json_safe(dt) == "2026-10-23T14:30:15"
    assert to_json_safe(d) == "2026-10-23"

    # Arbitrary objects must NOT be converted silently to string
    class ArbitraryClass:
        pass

    with pytest.raises(TypeError, match="is not JSON serializable"):
        to_json_safe(ArbitraryClass())


def test_to_json_safe_helper_nested_structures():
    dt1 = datetime(2026, 1, 1, 10, 0, 0)
    dt2 = datetime(2026, 2, 2, 12, 30, 0)
    d1 = date(2026, 3, 3)

    data = {
        "temperature": 0.0,
        "active": True,
        "timestamps": [dt1, {"inner_date": d1, "inner_list": [dt2, 123]}],
        "metadata": {
            "created": dt1,
            "tags": ("reproducibility", 1),
            "versions": {"v1": dt2},
        },
    }

    result = to_json_safe(data)

    assert result["temperature"] == 0.0
    assert type(result["temperature"]) is float
    assert result["active"] is True
    assert result["timestamps"][0] == "2026-01-01T10:00:00"
    assert result["timestamps"][1]["inner_date"] == "2026-03-03"
    assert result["timestamps"][1]["inner_list"][0] == "2026-02-02T12:30:00"
    assert result["timestamps"][1]["inner_list"][1] == 123
    assert result["metadata"]["created"] == "2026-01-01T10:00:00"
    assert result["metadata"]["tags"] == ["reproducibility", 1]
    assert result["metadata"]["versions"]["v1"] == "2026-02-02T12:30:00"


def test_create_experiment_with_db_provider_metadata_datetime(monkeypatch):
    monkeypatch.setattr(provider_service, "_url", lambda val: val.rstrip("/"))
    with TestClient(app) as client:
        # Create dataset and snapshot
        up = client.post(
            "/api/datasets/upload",
            files={"file": ("samples.jsonl", b'{"prompt":"test"}\n', "application/x-ndjson")},
        )
        assert up.status_code == 201, up.text
        dataset = up.json()
        snap = client.post(f"/api/datasets/{dataset['id']}/snapshots").json()

        # Create provider in database (whose metadata contains created_at and updated_at datetime objects)
        prov = client.post(
            "/api/providers",
            json={
                "name": "DB Provider Test",
                "provider_type": "openai_compatible",
                "base_url": "https://provider.example.com/v1",
                "default_model": "test-model",
            },
        ).json()

        # Create experiment using the database provider and temperature: 0.0
        exp_resp = client.post(
            "/api/experiments",
            json={
                "name": "Provider Datetime Regression Test",
                "dataset_snapshot_id": snap["id"],
                "agent_id": "mock-agent",
                "provider_id": prov["id"],
                "input_mapping": {"prompt": "text"},
                "agent_configuration": {"temperature": 0.0},
            },
        )
        assert exp_resp.status_code == 201, exp_resp.text
        exp = exp_resp.json()

        # Verify UI contract
        assert exp["name"] == "Provider Datetime Regression Test"
        assert exp["agent_configuration_snapshot"] == {"temperature": 0.0}
        assert exp["provider_id"] == prov["id"]

        # Verify persisted snapshot in database
        db = SessionLocal()
        try:
            db_exp = db.get(Experiment, exp["id"])
            assert db_exp is not None
            assert db_exp.agent_configuration_snapshot == {"temperature": 0.0}
            assert isinstance(db_exp.provider_metadata_snapshot, dict)
            assert isinstance(db_exp.provider_metadata_snapshot["created_at"], str)
            assert isinstance(db_exp.provider_metadata_snapshot["updated_at"], str)
            # Must be valid ISO strings
            datetime.fromisoformat(db_exp.provider_metadata_snapshot["created_at"])
            datetime.fromisoformat(db_exp.provider_metadata_snapshot["updated_at"])
        finally:
            db.close()

        # Verify manifest endpoint returns valid provider snapshot
        manifest_resp = client.get(f"/api/experiments/{exp['id']}/manifest")
        assert manifest_resp.status_code == 200, manifest_resp.text
        manifest = manifest_resp.json()
        assert manifest["provider"]["id"] == prov["id"]
        assert isinstance(manifest["provider"]["created_at"], str)


def test_create_experiment_with_nested_datetime_in_provider_metadata(monkeypatch):
    monkeypatch.setattr(provider_service, "_url", lambda val: val.rstrip("/"))
    with TestClient(app) as client:
        # Create dataset and snapshot
        up = client.post(
            "/api/datasets/upload",
            files={"file": ("samples2.jsonl", b'{"prompt":"test2"}\n', "application/x-ndjson")},
        )
        assert up.status_code == 201, up.text
        snap = client.post(f"/api/datasets/{up.json()['id']}/snapshots").json()

        # Create provider
        prov = client.post(
            "/api/providers",
            json={
                "name": "Nested Datetime Provider",
                "provider_type": "openai_compatible",
                "base_url": "https://provider2.example.com/v1",
                "default_model": "test-model-2",
            },
        ).json()

        # Patch provider metadata to return nested datetimes and dates in dicts/lists
        original_metadata = provider_service.metadata

        def patched_metadata(item):
            meta = original_metadata(item)
            meta["custom_nested"] = {
                "checked_at": datetime(2026, 10, 23, 12, 0, 0),
                "history": [
                    {"run_date": date(2026, 10, 22), "timestamp": datetime(2026, 10, 22, 9, 30, 0)}
                ],
                "numbers": [1, 2.5, 0.0],
            }
            return meta

        monkeypatch.setattr(provider_service, "metadata", patched_metadata)

        # Create experiment
        exp_resp = client.post(
            "/api/experiments",
            json={
                "name": "Nested Datetime Test",
                "dataset_snapshot_id": snap["id"],
                "agent_id": "mock-agent",
                "provider_id": prov["id"],
                "input_mapping": {"prompt": "text"},
                "agent_configuration": {"temperature": 0.0},
            },
        )
        assert exp_resp.status_code == 201, exp_resp.text
        exp_id = exp_resp.json()["id"]

        # Verify database record
        db = SessionLocal()
        try:
            db_exp = db.get(Experiment, exp_id)
            assert db_exp is not None
            custom = db_exp.provider_metadata_snapshot["custom_nested"]
            assert custom["checked_at"] == "2026-10-23T12:00:00"
            assert custom["history"][0]["run_date"] == "2026-10-22"
            assert custom["history"][0]["timestamp"] == "2026-10-22T09:30:00"
            assert custom["numbers"] == [1, 2.5, 0.0]
        finally:
            db.close()
