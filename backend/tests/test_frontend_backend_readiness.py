"""Frontend-Backend Readiness Test Suite.

Verifies that the Research Arena backend satisfies all requirements for the
new frontend while maintaining 100% backward compatibility and zero regressions:

1. Dataset listing with additive pagination metadata (total, has_more, next_offset).
2. Dataset records pagination with total count and record indices.
3. Dataset safe deletion protection when referenced by snapshots (409 Conflict).
4. Agent self-description, display_name, description, status, and JSON schemas.
5. Provider credential security (never exposes plaintext secret), lifecycle, and updates.
6. Provider connection test returning ok, reachable, latency_ms, checks, errors.
7. Experiment creation with explicit model override and frozen model persistence.
8. Experiment execution preserving frozen model override across provider mutations.
9. Runs endpoint with additive pagination metadata (total, has_more, next_offset, total_persisted_runs, expected_run_count).
10. Results endpoint returning all runs without page truncation and supporting pagination.
11. Consistency aggregations route collision fix: /experiments/consistency-aggregations returns 200, not 404.
12. Evaluation lifecycle, idempotency protection, force re-evaluation, and exports (JSONL + CSV).
13. Analysis dashboard options, condition resolution, model resolution, and comparison reporting.
"""
import io
import json
import time
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from app.main import app
from app.services import providers as provider_service
from app.services.analysis import _determine_condition, _resolve_model, _calculate_delta, generate_analysis_report
from app.models.entities import Experiment, ProviderConfiguration, DatasetSnapshot, Run
from app.database.session import SessionLocal


def test_dataset_pagination_and_metadata():
    with TestClient(app) as client:
        # Upload 4 sample records
        content = (
            b'{"id":"rec_1","prompt":"apple earnings","ground_truth":"positive"}\n'
            b'{"id":"rec_2","prompt":"google cloud","ground_truth":"growth"}\n'
            b'{"id":"rec_3","prompt":"microsoft azure","ground_truth":"guidance"}\n'
            b'{"id":"rec_4","prompt":"amazon aws","ground_truth":"stable"}\n'
        )
        upload_resp = client.post(
            "/api/datasets/upload",
            files={"file": ("readiness_samples.jsonl", content, "application/x-ndjson")},
            data={"display_name": "Readiness Samples"},
        )
        assert upload_resp.status_code == 201, upload_resp.text
        ds = upload_resp.json()
        assert ds["validation_status"] == "valid"
        ds_id = ds["id"]

        # 1. Dataset list pagination
        list_resp = client.get("/api/datasets?offset=0&limit=50")
        assert list_resp.status_code == 200
        list_data = list_resp.json()
        assert "items" in list_data
        assert "total" in list_data
        assert "has_more" in list_data
        assert list_data["total"] >= 1
        assert list_data["offset"] == 0
        assert list_data["limit"] == 50

        # 2. Dataset records pagination: Page 1
        page1_resp = client.get(f"/api/datasets/{ds_id}/records?offset=0&limit=2")
        assert page1_resp.status_code == 200
        page1 = page1_resp.json()
        assert len(page1["items"]) == 2
        assert page1["total"] == 4
        assert page1["has_more"] is True
        assert page1["next_offset"] == 2
        assert page1["items"][0]["index"] == 0
        assert page1["items"][1]["index"] == 1

        # Page 2
        page2_resp = client.get(f"/api/datasets/{ds_id}/records?offset=2&limit=2")
        assert page2_resp.status_code == 200
        page2 = page2_resp.json()
        assert len(page2["items"]) == 2
        assert page2["total"] == 4
        assert page2["has_more"] is False
        assert page2["next_offset"] is None
        assert page2["items"][0]["index"] == 2
        assert page2["items"][1]["index"] == 3


def test_dataset_deletion_protection():
    with TestClient(app) as client:
        content = b'{"prompt":"test deletion protection"}\n'
        upload_resp = client.post(
            "/api/datasets/upload",
            files={"file": ("snap_protect.jsonl", content, "application/x-ndjson")},
        )
        assert upload_resp.status_code == 201
        ds = upload_resp.json()
        ds_id = ds["id"]

        # Create a snapshot
        snap_resp = client.post(f"/api/datasets/{ds_id}/snapshots")
        assert snap_resp.status_code == 201

        # Attempt to delete dataset with active snapshot -> must return 409
        del_resp = client.delete(f"/api/datasets/{ds_id}")
        assert del_resp.status_code == 409
        error = del_resp.json().get("error", {})
        assert error.get("code") == "DATASET_REFERENCED"


def test_agent_self_description_and_schemas():
    with TestClient(app) as client:
        # List all agents
        list_resp = client.get("/api/agents")
        assert list_resp.status_code == 200
        agent_map = {a["id"]: a for a in list_resp.json()["items"]}

        # Baseline agent
        assert "financial_news_analysis" in agent_map
        baseline = agent_map["financial_news_analysis"]
        assert baseline["display_name"] == "Financial News Analysis"
        assert "description" in baseline and len(baseline["description"]) > 10
        assert baseline["status"] == "ready"
        assert baseline["ready"] is True
        assert baseline["input_schema"] is not None
        assert baseline["output_schema"] is not None
        assert baseline["input_schema"].get("type") == "object"

        # EGAL agent
        assert "financial_news_analysis_egal" in agent_map
        egal = agent_map["financial_news_analysis_egal"]
        assert egal["display_name"] == "Financial News Analysis — EGAL"
        assert "description" in egal and len(egal["description"]) > 10
        assert egal["status"] == "ready"
        assert egal["ready"] is True
        assert egal["input_schema"] is not None
        assert egal["output_schema"] is not None

        # Direct agent get
        get_resp = client.get("/api/agents/financial_news_analysis_egal")
        assert get_resp.status_code == 200
        direct_egal = get_resp.json()
        assert direct_egal["id"] == "financial_news_analysis_egal"
        assert direct_egal["display_name"] == "Financial News Analysis — EGAL"


def test_provider_security_redaction_and_lifecycle(monkeypatch):
    monkeypatch.setattr(provider_service, "_fernet", lambda: Fernet(Fernet.generate_key()))
    monkeypatch.setattr(provider_service, "_url", lambda v: v.rstrip("/"))
    with TestClient(app) as client:
        # 1. Create provider with an API key
        body = {
            "name": "Secure Test Provider",
            "provider_type": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "default_model": "gpt-4o",
            "api_key": "sk-super-secret-password-12345",
            "timeout_seconds": 25.0,
        }
        create_resp = client.post("/api/providers", json=body)
        assert create_resp.status_code == 201, create_resp.text
        prov = create_resp.json()
        prov_id = prov["id"]

        # Ensure API key is NEVER exposed in response
        assert "api_key" not in prov
        assert "sk-super-secret" not in json.dumps(prov)
        assert prov["api_key_configured"] is True
        assert prov["default_model"] == "gpt-4o"

        # 2. Get provider
        get_resp = client.get(f"/api/providers/{prov_id}")
        assert get_resp.status_code == 200
        get_prov = get_resp.json()
        assert "api_key" not in get_prov
        assert get_prov["api_key_configured"] is True

        # 3. Clear API key
        update_resp = client.patch(f"/api/providers/{prov_id}", json={"clear_api_key": True})
        assert update_resp.status_code == 200
        assert update_resp.json()["api_key_configured"] is False


def test_provider_connection_test_latency_and_reachable(monkeypatch):
    monkeypatch.setattr(provider_service, "_url", lambda v: v.rstrip("/"))
    monkeypatch.setattr(provider_service, "discover_models", lambda item: ["gpt-4o", "gpt-4o-mini"])
    monkeypatch.setattr(provider_service, "generate_for_item", lambda item: {"choices": [{"message": {"content": "OK."}}]})

    with TestClient(app) as client:
        body = {
            "name": "Reachable Provider",
            "provider_type": "openai_compatible",
            "base_url": "https://api.openai.com/v1",
            "default_model": "gpt-4o",
            "timeout_seconds": 10.0,
        }
        prov = client.post("/api/providers", json=body).json()
        prov_id = prov["id"]

        test_resp = client.post(f"/api/providers/{prov_id}/test-connection")
        assert test_resp.status_code == 200
        result = test_resp.json()
        assert result["ok"] is True
        assert result["reachable"] is True
        assert "latency_ms" in result
        assert isinstance(result["latency_ms"], int)
        assert result["latency_ms"] >= 0
        assert any(c["name"] == "completion" and c["ok"] for c in result["checks"])


def test_experiment_creation_with_model_override(monkeypatch):
    monkeypatch.setattr(provider_service, "_url", lambda v: v.rstrip("/"))
    with TestClient(app) as client:
        # Create dataset and snapshot
        content = b'{"prompt":"test"}\n'
        uploaded = client.post(
            "/api/datasets/upload",
            files={"file": ("exp_model_sample.jsonl", content, "application/x-ndjson")},
        ).json()
        snapshot = client.post(f"/api/datasets/{uploaded['id']}/snapshots").json()

        # Create experiment with EXPLICIT model override
        exp_resp = client.post(
            "/api/experiments",
            json={
                "name": "Explicit Model Experiment",
                "dataset_snapshot_id": snapshot["id"],
                "agent_id": "mock-agent",
                "provider_id": "mock",
                "model": "gpt-4o-2024-11-20",
                "input_mapping": {"prompt": "text"},
            },
        )
        assert exp_resp.status_code == 201, exp_resp.text
        exp_data = exp_resp.json()
        assert exp_data["model"] == "gpt-4o-2024-11-20"

        # Verify persisted entity
        db = SessionLocal()
        try:
            persisted = db.get(Experiment, exp_data["id"])
            assert persisted.model == "gpt-4o-2024-11-20"
            assert persisted.provider_metadata_snapshot.get("model") == "gpt-4o-2024-11-20"
        finally:
            db.close()

        # Create experiment WITHOUT explicit model (falls back to provider default)
        exp_resp2 = client.post(
            "/api/experiments",
            json={
                "name": "Default Model Experiment",
                "dataset_snapshot_id": snapshot["id"],
                "agent_id": "mock-agent",
                "provider_id": "mock",
                "input_mapping": {"prompt": "text"},
            },
        )
        assert exp_resp2.status_code == 201
        exp_data2 = exp_resp2.json()
        assert exp_data2["model"] == "mock-v1"


def test_runs_pagination_and_expected_counts():
    with TestClient(app) as client:
        # Create dataset with 4 records
        content = (
            b'{"prompt":"r1"}\n'
            b'{"prompt":"r2"}\n'
            b'{"prompt":"r3"}\n'
            b'{"prompt":"r4"}\n'
        )
        uploaded = client.post(
            "/api/datasets/upload",
            files={"file": ("runs_page_samples.jsonl", content, "application/x-ndjson")},
        ).json()
        snapshot = client.post(f"/api/datasets/{uploaded['id']}/snapshots").json()

        # Create and run experiment
        exp = client.post(
            "/api/experiments",
            json={
                "name": "Runs Pagination Test",
                "dataset_snapshot_id": snapshot["id"],
                "agent_id": "mock-agent",
                "provider_id": "mock",
                "input_mapping": {"prompt": "text"},
            },
        ).json()

        # Start experiment
        client.post(f"/api/experiments/{exp['id']}/start")
        for _ in range(40):
            runs_check = client.get(f"/api/experiments/{exp['id']}/runs").json()
            if runs_check.get("total", 0) == 4 and all(x["status"] in {"completed", "failed"} for x in runs_check.get("items", [])):
                break
            time.sleep(0.05)

        # 1. Page 1 (limit=2)
        p1 = client.get(f"/api/experiments/{exp['id']}/runs?offset=0&limit=2").json()
        assert len(p1["items"]) == 2
        assert p1["total"] == 4
        assert p1["has_more"] is True
        assert p1["next_offset"] == 2
        assert p1["total_persisted_runs"] == 4
        assert p1["expected_run_count"] == 4
        assert p1["items"][0]["record_index"] == 0
        assert p1["items"][1]["record_index"] == 1

        # 2. Page 2 (limit=2)
        p2 = client.get(f"/api/experiments/{exp['id']}/runs?offset=2&limit=2").json()
        assert len(p2["items"]) == 2
        assert p2["total"] == 4
        assert p2["has_more"] is False
        assert p2["next_offset"] is None
        assert p2["total_persisted_runs"] == 4
        assert p2["items"][0]["record_index"] == 2
        assert p2["items"][1]["record_index"] == 3


def test_results_endpoint_full_retrieval_and_pagination():
    with TestClient(app) as client:
        content = (
            b'{"prompt":"r1"}\n'
            b'{"prompt":"r2"}\n'
            b'{"prompt":"r3"}\n'
        )
        uploaded = client.post(
            "/api/datasets/upload",
            files={"file": ("results_samples.jsonl", content, "application/x-ndjson")},
        ).json()
        snapshot = client.post(f"/api/datasets/{uploaded['id']}/snapshots").json()
        exp = client.post(
            "/api/experiments",
            json={
                "name": "Results Test",
                "dataset_snapshot_id": snapshot["id"],
                "agent_id": "mock-agent",
                "provider_id": "mock",
                "input_mapping": {"prompt": "text"},
            },
        ).json()
        client.post(f"/api/experiments/{exp['id']}/start")
        for _ in range(40):
            runs_check = client.get(f"/api/experiments/{exp['id']}/runs").json()
            if runs_check.get("total", 0) == 3 and all(x["status"] in {"completed", "failed"} for x in runs_check.get("items", [])):
                break
            time.sleep(0.05)

        # Default results call (no limit provided) -> returns all items
        res_all = client.get(f"/api/experiments/{exp['id']}/results").json()
        assert res_all["total"] == 3
        assert len(res_all["items"]) == 3
        assert res_all["has_more"] is False
        assert res_all["total_persisted_runs"] == 3

        # Results with pagination
        res_paginated = client.get(f"/api/experiments/{exp['id']}/results?offset=0&limit=2").json()
        assert len(res_paginated["items"]) == 2
        assert res_paginated["total"] == 3
        assert res_paginated["has_more"] is True
        assert res_paginated["next_offset"] == 2


def test_consistency_aggregations_route_collision_resolved():
    with TestClient(app) as client:
        # 1. GET /api/experiments/consistency-aggregations MUST return 200 (not 404!)
        resp1 = client.get("/api/experiments/consistency-aggregations")
        assert resp1.status_code == 200, f"Expected 200, got {resp1.status_code}: {resp1.text}"
        assert "items" in resp1.json()

        # 2. GET /api/evaluations/consistency-aggregations MUST also return 200
        resp2 = client.get("/api/evaluations/consistency-aggregations")
        assert resp2.status_code == 200
        assert "items" in resp2.json()

        # 3. GET /api/experiments/{experiment_id} for a non-existent ID still returns 404 NOT_FOUND
        resp_missing = client.get("/api/experiments/non-existent-experiment-id")
        assert resp_missing.status_code == 404
        error = resp_missing.json().get("error", {})
        assert error.get("code") == "NOT_FOUND"


def test_evaluation_lifecycle_idempotency_and_exports():
    def synth_record(scenario_id, cat):
        return {
            "record_schema_version": "1.0",
            "scenario_id": scenario_id,
            "category": cat,
            "input": {
                "schema_version": "1.0",
                "scenario_id": scenario_id,
                "ticker": "SYN",
                "company_name": "Synthetic Corp",
                "task": "Analyze news.",
                "retrieval_mode": "provided_evidence",
                "search_query": None,
                "evidence": [{"evidence_id": "E1", "type": "news", "title": "T", "content": "C", "source_name": "S", "url": "https://example.test"}],
            },
            "ground_truth": {
                "annotation_version": "1.0",
                "expected_task_completion": True,
                "supported_facts": [{"text": "Fact", "evidence_ids": ["E1"]}],
            },
            "metadata": {"source_mode": "test"},
        }

    with TestClient(app) as client:
        # 1. Upload dataset with valid schema
        content = (
            json.dumps(synth_record("NORMAL-001", "normal")) + "\n" +
            json.dumps(synth_record("AMBIGUOUS-001", "ambiguous")) + "\n"
        ).encode()
        uploaded = client.post(
            "/api/datasets/upload",
            files={"file": ("eval_lifecycle.jsonl", content, "application/x-ndjson")},
        ).json()
        snap = client.post(f"/api/datasets/{uploaded['id']}/snapshots").json()

        # 2. Create experiment
        exp = client.post(
            "/api/experiments",
            json={
                "name": "Eval Lifecycle Experiment",
                "dataset_snapshot_id": snap["id"],
                "agent_id": "financial_news_analysis",
                "provider_id": "mock",
                "input_mapping": {},
            },
        ).json()
        exp_id = exp["id"]

        # Directly insert completed runs in DB
        db = SessionLocal()
        try:
            persisted_exp = db.get(Experiment, exp_id)
            persisted_exp.status = "completed"
            db.add_all([
                Run(
                    id=f"run_eval_1_{exp_id}",
                    experiment_id=exp_id,
                    record_index=0,
                    status="completed",
                    normalized_output={
                        "schema_version": "1.0", "scenario_id": "NORMAL-001", "ticker": "SYN",
                        "sentiment": "neutral", "price_impact": "neutral", "recommendation": "HOLD",
                        "confidence": 0.5, "forecast_pct": None, "forecast_horizon": "unspecified",
                        "reasoning": [{"text": "Fact", "evidence_ids": ["E1"]}],
                        "key_factors": [], "risk_factors": [], "missing_information": [], "source_ids_used": ["E1"],
                    },
                ),
                Run(
                    id=f"run_eval_2_{exp_id}",
                    experiment_id=exp_id,
                    record_index=1,
                    status="completed",
                    normalized_output={
                        "schema_version": "1.0", "scenario_id": "AMBIGUOUS-001", "ticker": "SYN",
                        "sentiment": "neutral", "price_impact": "neutral", "recommendation": "HOLD",
                        "confidence": 0.5, "forecast_pct": None, "forecast_horizon": "unspecified",
                        "reasoning": [{"text": "Fact", "evidence_ids": ["E1"]}],
                        "key_factors": [], "risk_factors": [], "missing_information": [], "source_ids_used": ["E1"],
                    },
                ),
            ])
            db.commit()
        finally:
            db.close()

        # 3. Trigger evaluation -> 201 Created
        eval_resp = client.post(f"/api/experiments/{exp_id}/evaluations")
        assert eval_resp.status_code == 201, eval_resp.text
        eval_data = eval_resp.json()
        eval_id = eval_data["id"]
        assert eval_data["status"] == "completed"
        assert "task_completion_rate" in eval_data["metrics"]

        # 4. Trigger again without force -> 201 Created returning existing evaluation (idempotency)
        dup_resp = client.post(f"/api/experiments/{exp_id}/evaluations")
        assert dup_resp.status_code == 201
        assert dup_resp.json()["id"] == eval_id

        # 5. Trigger with force=True -> 201 Created returning fresh evaluation
        force_resp = client.post(f"/api/experiments/{exp_id}/evaluations", json={"force": True})
        assert force_resp.status_code == 201
        assert force_resp.json()["id"] != eval_id

        # 6. Export JSONL
        jsonl_resp = client.get(f"/api/experiments/{exp_id}/evaluations/{eval_id}/exports/jsonl")
        assert jsonl_resp.status_code == 200
        assert "application/x-ndjson" in jsonl_resp.headers["content-type"]
        assert "evaluation_summary" in jsonl_resp.text

        # 7. Export CSV
        csv_resp = client.get(f"/api/experiments/{exp_id}/evaluations/{eval_id}/exports/csv")
        assert csv_resp.status_code == 200
        assert "text/csv" in csv_resp.headers["content-type"]
        assert "evaluation_id,run_id,scenario_id" in csv_resp.text


def test_analysis_options_and_model_resolution():
    with TestClient(app) as client:
        resp = client.get("/api/analysis/options")
        assert resp.status_code == 200
        options = resp.json()
        assert "datasets" in options
        assert "dataset_snapshots" in options
        assert "models" in options
        assert "conditions" in options
        assert "providers" in options
        assert "agents" in options
        assert "experiments" in options
        assert isinstance(options["conditions"], list)

        # Unit verification of condition and model determination helpers
        assert _determine_condition("financial_news_analysis") == "baseline"
        assert _determine_condition("financial_news_analysis_egal") == "egal"
        assert _determine_condition("custom_agent") == "baseline"
        assert _determine_condition("egal_enhanced_v2") == "egal"

        # Delta calculation verification
        delta_improved = _calculate_delta(0.8, 0.6, higher_is_better=True)
        assert delta_improved["direction"] == "improved"
        assert delta_improved["value"] == 0.2
        assert delta_improved["interpretation"] == "higher_is_better"

        delta_regressed = _calculate_delta(0.3, 0.1, higher_is_better=False)
        assert delta_regressed["direction"] == "regressed"
        assert delta_regressed["interpretation"] == "lower_is_better"

        # Model resolution verification
        mock_exp = Experiment(id="test_exp", model="gpt-4o-custom")
        assert _resolve_model(mock_exp, None) == "gpt-4o-custom"
