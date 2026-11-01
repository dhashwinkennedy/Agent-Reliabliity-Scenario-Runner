"""Tests for Experiment Repetitions and Baseline-EGAL Grouping.

Verifies all required behaviors:
1. Two or more repetitions preserve separate runs and evaluations.
2. Baseline and EGAL repetitions are grouped correctly without mixing their results.
3. Failed runs remain visible and older results are unchanged.
4. Repetition uses original frozen configuration even if provider defaults later change.
5. Idempotency and duplicate prevention for start/rerun requests.
6. Offline evaluation evaluates each repetition independently without invoking LLM/providers.
7. Repetition and Group export endpoints (JSONL + CSV).
"""
import io
import json
import time
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.database.session import SessionLocal
from app.models.entities import Experiment, Run, Evaluation, RunEvaluation, ExperimentRepetition, ExperimentGroup, ProviderConfiguration
from app.services import evaluation as evaluation_service
from app.services import experiments as experiment_service
from app.integrations.registry import providers


def _make_sample_dataset(folder: Path, count: int = 4) -> str:
    """Helper to upload a test dataset and create a snapshot."""
    with TestClient(app) as client:
        lines = []
        for i in range(count):
            lines.append(json.dumps({
                "scenario_id": f"SCENARIO-{i}",
                "category": "normal" if i % 2 == 0 else "ambiguous",
                "input": {
                    "headline": f"Company {i} reports quarterly earnings growth",
                    "article": f"Company {i} revenues grew by 15 percent year on year.",
                },
                "ground_truth": {"recommendation": "BUY", "sentiment": "positive"},
            }))
        content = "\n".join(lines).encode("utf-8") + b"\n"
        upload_resp = client.post(
            "/api/datasets/upload",
            files={"file": (f"test_data_{time.time_ns()}.jsonl", content, "application/x-ndjson")},
            data={"display_name": "Test Dataset Repetitions"},
        )
        assert upload_resp.status_code == 201, upload_resp.text
        ds_id = upload_resp.json()["id"]

        snap_resp = client.post(f"/api/datasets/{ds_id}/snapshots")
        assert snap_resp.status_code == 201, snap_resp.text
        return snap_resp.json()["id"]


def test_two_or_more_repetitions_preserve_separate_runs_and_evaluations():
    """Verify that rerun creates distinct repetition and run records, preserving earlier runs and evaluations."""
    with TemporaryDirectory() as tmpdir:
        snap_id = _make_sample_dataset(Path(tmpdir), count=3)

        with TestClient(app) as client:
            # 1. Create an experiment
            exp_resp = client.post("/api/experiments", json={
                "name": "Multi-Repetition Experiment",
                "dataset_snapshot_id": snap_id,
                "agent_id": "financial_news_analysis",
                "provider_id": "mock",
                "model": "mock-v1",
                "input_mapping": {},
            })
            assert exp_resp.status_code == 201, exp_resp.text
            exp_id = exp_resp.json()["id"]

            # 2. Start Repetition 1
            start_resp = client.post(f"/api/experiments/{exp_id}/start")
            assert start_resp.status_code == 200

            # Wait for repetition 1 to complete
            for _ in range(50):
                check = client.get(f"/api/experiments/{exp_id}/runs?repetition_index=1").json()
                if check.get("total", 0) == 3 and all(r["status"] in {"completed", "failed"} for r in check.get("items", [])):
                    break
                time.sleep(0.05)

            # Evaluate Repetition 1
            eval1_resp = client.post(f"/api/experiments/{exp_id}/evaluations", json={"repetition_index": 1})
            assert eval1_resp.status_code == 201, eval1_resp.text
            eval1 = eval1_resp.json()
            assert eval1["repetition_index"] == 1
            eval1_id = eval1["id"]

            # Snapshot Repetition 1 runs
            rep1_runs_resp = client.get(f"/api/experiments/{exp_id}/repetitions/1/runs").json()
            assert rep1_runs_resp["total"] == 3
            rep1_run_ids = {r["id"] for r in rep1_runs_resp["items"]}
            assert len(rep1_run_ids) == 3

            # 3. Trigger Rerun (Repetition 2) via single-button endpoint
            rerun_resp = client.post(f"/api/experiments/{exp_id}/rerun")
            assert rerun_resp.status_code == 201, rerun_resp.text
            rerun_data = rerun_resp.json()
            assert rerun_data["repetition_index"] == 2
            rep2_id = rerun_data["id"]

            # Wait for repetition 2 to complete
            for _ in range(50):
                check = client.get(f"/api/experiments/{exp_id}/runs?repetition_index=2").json()
                if check.get("total", 3) == 3 and all(r["status"] in {"completed", "failed"} for r in check.get("items", [])):
                    break
                time.sleep(0.05)

            # Evaluate Repetition 2
            eval2_resp = client.post(f"/api/experiments/{exp_id}/evaluations", json={"repetition_index": 2})
            assert eval2_resp.status_code == 201, eval2_resp.text
            eval2 = eval2_resp.json()
            assert eval2["repetition_index"] == 2
            eval2_id = eval2["id"]

            # Evaluations must be distinct
            assert eval1_id != eval2_id

            # Repetition 2 runs must be completely distinct from Repetition 1 runs
            rep2_runs_resp = client.get(f"/api/experiments/{exp_id}/repetitions/2/runs").json()
            assert rep2_runs_resp["total"] == 3
            rep2_run_ids = {r["id"] for r in rep2_runs_resp["items"]}
            assert len(rep2_run_ids) == 3
            assert rep1_run_ids.isdisjoint(rep2_run_ids), "Runs between repetitions must never collide"

            # Check Repetition 1 runs remain completely unchanged
            rep1_runs_check = client.get(f"/api/experiments/{exp_id}/repetitions/1/runs").json()
            assert {r["id"] for r in rep1_runs_check["items"]} == rep1_run_ids

            # Check Repetition history endpoint
            history_resp = client.get(f"/api/experiments/{exp_id}/repetitions")
            assert history_resp.status_code == 200
            history = history_resp.json()
            assert history["total"] == 2
            indices = [r["repetition_index"] for r in history["items"]]
            assert indices == [1, 2]
            assert history["items"][0]["evaluation_id"] == eval1_id
            assert history["items"][1]["evaluation_id"] == eval2_id


def test_baseline_and_egal_grouping_without_mixing_results():
    """Verify Baseline and EGAL are grouped under a shared identifier with separate histories and comparative metrics."""
    with TemporaryDirectory() as tmpdir:
        snap_id = _make_sample_dataset(Path(tmpdir), count=2)

        with TestClient(app) as client:
            # 1. Create a group via group API
            group_payload = {
                "name": "Financial News Alpha Benchmark",
                "dataset_snapshot_id": snap_id,
                "provider_id": "mock",
                "model": "mock-v1",
                "auto_start": True,
            }
            create_group_resp = client.post("/api/experiment-groups", json=group_payload)
            assert create_group_resp.status_code == 201, create_group_resp.text
            grp_data = create_group_resp.json()
            group_id = grp_data["group_id"]
            assert grp_data["name"] == "Financial News Alpha Benchmark"

            b_exp_id = grp_data["baseline"]["experiment"]["id"]
            e_exp_id = grp_data["egal"]["experiment"]["id"]
            assert b_exp_id != e_exp_id

            # Wait for both experiments to finish execution
            for _ in range(50):
                b_runs = client.get(f"/api/experiments/{b_exp_id}/runs").json()
                e_runs = client.get(f"/api/experiments/{e_exp_id}/runs").json()
                b_done = b_runs.get("total", 0) == 2 and all(r["status"] in {"completed", "failed"} for r in b_runs.get("items", []))
                e_done = e_runs.get("total", 0) == 2 and all(r["status"] in {"completed", "failed"} for r in e_runs.get("items", []))
                if b_done and e_done:
                    break
                time.sleep(0.05)

            # Evaluate both independently
            ev_b_resp = client.post(f"/api/experiments/{b_exp_id}/evaluations")
            assert ev_b_resp.status_code == 201
            ev_e_resp = client.post(f"/api/experiments/{e_exp_id}/evaluations")
            assert ev_e_resp.status_code == 201

            # Verify runs are distinct
            b_runs_items = client.get(f"/api/experiments/{b_exp_id}/runs").json()["items"]
            e_runs_items = client.get(f"/api/experiments/{e_exp_id}/runs").json()["items"]
            b_ids = {r["id"] for r in b_runs_items}
            e_ids = {r["id"] for r in e_runs_items}
            assert b_ids.isdisjoint(e_ids), "Baseline and EGAL runs must never mix"

            # Query group details
            group_detail = client.get(f"/api/experiment-groups/{group_id}").json()
            assert group_detail["group_id"] == group_id
            assert group_detail["baseline"]["repetition_count"] == 1
            assert group_detail["egal"]["repetition_count"] == 1

            comparison = group_detail["comparison"]
            assert comparison["available"] is True
            assert "delta" in comparison
            assert "task_completion_rate" in comparison["delta"]
            assert "unsupported_action_rate" in comparison["delta"]


def test_grouping_rejects_incompatible_experiments():
    """Verify grouping rejects experiments with mismatched snapshot, provider, or model conditions."""
    with TemporaryDirectory() as tmpdir:
        snap_id_1 = _make_sample_dataset(Path(tmpdir), count=2)
        snap_id_2 = _make_sample_dataset(Path(tmpdir), count=2)

        with TestClient(app) as client:
            exp1 = client.post("/api/experiments", json={
                "name": "Exp 1",
                "dataset_snapshot_id": snap_id_1,
                "agent_id": "financial_news_analysis",
                "provider_id": "mock",
                "model": "mock-v1",
            }).json()

            # Mismatched snapshot
            exp2 = client.post("/api/experiments", json={
                "name": "Exp 2 Mismatched Snapshot",
                "dataset_snapshot_id": snap_id_2,
                "agent_id": "financial_news_analysis_egal",
                "provider_id": "mock",
                "model": "mock-v1",
            }).json()

            link_resp = client.post("/api/experiment-groups/link", json={
                "group_name": "Incompatible Group",
                "experiment_ids": [exp1["id"], exp2["id"]],
            })
            assert link_resp.status_code == 422
            assert link_resp.json()["error"]["code"] == "INCOMPATIBLE_EXPERIMENT_GROUP"


def test_failed_runs_remain_visible_and_older_results_unchanged():
    """Verify failed runs are preserved in historical repetitions and visible in evaluation manifests."""
    with TemporaryDirectory() as tmpdir:
        snap_id = _make_sample_dataset(Path(tmpdir), count=2)

        with TestClient(app) as client:
            exp_resp = client.post("/api/experiments", json={
                "name": "Failure Visibility Experiment",
                "dataset_snapshot_id": snap_id,
                "agent_id": "mock-agent",
                "provider_id": "mock",
                "model": "mock-v1",
                "input_mapping": {"headline": "text"},
            })
            exp_id = exp_resp.json()["id"]

            # Start Repetition 1
            client.post(f"/api/experiments/{exp_id}/start")
            for _ in range(40):
                r = client.get(f"/api/experiments/{exp_id}/runs?repetition_index=1").json()
                if r.get("total", 0) == 2 and all(x["status"] in {"completed", "failed"} for x in r.get("items", [])):
                    break
                time.sleep(0.05)

            # Manually inject a failure into one run to test failure visibility
            db = SessionLocal()
            try:
                run1 = db.query(Run).filter_by(experiment_id=exp_id, record_index=1, repetition_index=1).first()
                run1.status = "failed"
                run1.error = {"code": "PROVIDER_TIMEOUT", "message": "Simulated connection timeout"}
                db.commit()
            finally:
                db.close()

            # Evaluate Repetition 1
            eval1 = client.post(f"/api/experiments/{exp_id}/evaluations", json={"repetition_index": 1, "force": True}).json()
            assert eval1["manifest"]["failed_run_count"] == 1
            assert eval1["manifest"]["evaluation_status"] == "INCOMPLETE"

            # Rerun -> Repetition 2
            rerun_resp = client.post(f"/api/experiments/{exp_id}/rerun")
            assert rerun_resp.status_code == 201

            for _ in range(40):
                r = client.get(f"/api/experiments/{exp_id}/runs?repetition_index=2").json()
                if r.get("total", 0) == 2 and all(x["status"] in {"completed", "failed"} for x in r.get("items", [])):
                    break
                time.sleep(0.05)

            # Evaluate Repetition 2
            eval2 = client.post(f"/api/experiments/{exp_id}/evaluations", json={"repetition_index": 2}).json()
            assert eval2["repetition_index"] == 2

            # Verify Repetition 1 still has failed run and failed manifest
            rep1_runs = client.get(f"/api/experiments/{exp_id}/repetitions/1/runs").json()["items"]
            assert any(r["status"] == "failed" and r["error"]["code"] == "PROVIDER_TIMEOUT" for r in rep1_runs)
            eval1_check = client.get(f"/api/experiments/{exp_id}/repetitions/1/evaluation").json()
            assert eval1_check["manifest"]["failed_run_count"] == 1


def test_repetition_uses_frozen_configuration_when_provider_mutates():
    """Verify that a repetition uses the original frozen experiment configuration even if provider default changes."""
    with TemporaryDirectory() as tmpdir:
        snap_id = _make_sample_dataset(Path(tmpdir), count=2)

        with TestClient(app) as client:
            # Create a custom provider
            prov_payload = {
                "name": "Mutating Provider",
                "provider_type": "openai_compatible",
                "base_url": "https://api.openai.com/v1",
                "default_model": "initial-frozen-model-v1",
                "timeout_seconds": 30.0,
            }
            prov_resp = client.post("/api/providers", json=prov_payload)
            assert prov_resp.status_code == 201
            prov_id = prov_resp.json()["id"]

            # Create experiment using provider
            exp_resp = client.post("/api/experiments", json={
                "name": "Frozen Config Experiment",
                "dataset_snapshot_id": snap_id,
                "agent_id": "mock-agent",
                "provider_id": prov_id,
                "model": "initial-frozen-model-v1",
                "input_mapping": {"headline": "text"},
            })
            exp_id = exp_resp.json()["id"]

            # Start and finish Repetition 1
            client.post(f"/api/experiments/{exp_id}/start")
            for _ in range(40):
                r = client.get(f"/api/experiments/{exp_id}/runs?repetition_index=1").json()
                if r.get("total", 0) == 2 and all(x["status"] in {"completed", "failed"} for x in r.get("items", [])):
                    break
                time.sleep(0.05)

            # Mutate provider default model
            patch_resp = client.patch(f"/api/providers/{prov_id}", json={"default_model": "mutated-new-model-v2"})
            assert patch_resp.status_code == 200
            assert patch_resp.json()["default_model"] == "mutated-new-model-v2"

            # Rerun experiment -> Repetition 2
            rerun_resp = client.post(f"/api/experiments/{exp_id}/rerun")
            assert rerun_resp.status_code == 201
            rep2_data = rerun_resp.json()
            assert rep2_data["repetition_index"] == 2

            # The experiment's frozen model must remain initial-frozen-model-v1
            exp_get = client.get(f"/api/experiments/{exp_id}").json()
            assert exp_get["model"] == "initial-frozen-model-v1"


def test_rerun_idempotency_and_duplicate_prevention():
    """Verify that repeated requests with same idempotency key do not create duplicate executions."""
    with TemporaryDirectory() as tmpdir:
        snap_id = _make_sample_dataset(Path(tmpdir), count=2)

        with TestClient(app) as client:
            exp_resp = client.post("/api/experiments", json={
                "name": "Idempotent Experiment",
                "dataset_snapshot_id": snap_id,
                "agent_id": "financial_news_analysis",
                "provider_id": "mock",
                "model": "mock-v1",
            })
            exp_id = exp_resp.json()["id"]

            # Trigger repetition with idempotency key
            idempotency_key = "token-test-xyz-987"
            rep_resp1 = client.post(
                f"/api/experiments/{exp_id}/rerun",
                json={"idempotency_key": idempotency_key},
            )
            assert rep_resp1.status_code == 201
            rep1 = rep_resp1.json()

            # Immediate retry with same key (simulating network retry / double click)
            rep_resp2 = client.post(
                f"/api/experiments/{exp_id}/rerun",
                json={"idempotency_key": idempotency_key},
            )
            assert rep_resp2.status_code == 201
            rep2 = rep_resp2.json()

            # Must return the SAME repetition ID and index
            assert rep1["id"] == rep2["id"]
            assert rep1["repetition_index"] == rep2["repetition_index"]

            # Confirm total repetitions in DB is exactly 1
            reps_list = client.get(f"/api/experiments/{exp_id}/repetitions").json()
            assert reps_list["total"] == 1


def test_offline_evaluation_does_not_call_llm(monkeypatch):
    """Verify offline evaluation evaluates repetitions strictly from saved runs without calling LLM."""
    with TemporaryDirectory() as tmpdir:
        snap_id = _make_sample_dataset(Path(tmpdir), count=2)

        with TestClient(app) as client:
            exp_resp = client.post("/api/experiments", json={
                "name": "Offline Eval Experiment",
                "dataset_snapshot_id": snap_id,
                "agent_id": "financial_news_analysis",
                "provider_id": "mock",
                "model": "mock-v1",
            })
            exp_id = exp_resp.json()["id"]

            client.post(f"/api/experiments/{exp_id}/start")
            for _ in range(40):
                r = client.get(f"/api/experiments/{exp_id}/runs?repetition_index=1").json()
                if r.get("total", 0) == 2 and all(x["status"] in {"completed", "failed"} for x in r.get("items", [])):
                    break
                time.sleep(0.05)

            # Disallow any provider / LLM calls
            def forbid_call(*args, **kwargs):
                raise RuntimeError("LLM was called during offline evaluation!")
            monkeypatch.setattr(providers["mock"], "complete", forbid_call)
            import app.services.providers as ps
            if hasattr(ps, "generate"):
                monkeypatch.setattr(ps, "generate", forbid_call)

            # Evaluate repetition 1 offline
            eval_resp = client.post(f"/api/experiments/{exp_id}/evaluations", json={"repetition_index": 1})
            assert eval_resp.status_code == 201
            assert eval_resp.json()["status"] == "completed"


def test_repetition_and_group_exports():
    """Verify export endpoints for repetitions and experiment groups return valid JSONL and CSV."""
    with TemporaryDirectory() as tmpdir:
        snap_id = _make_sample_dataset(Path(tmpdir), count=2)

        with TestClient(app) as client:
            group_payload = {
                "name": "Export Benchmark Group",
                "dataset_snapshot_id": snap_id,
                "provider_id": "mock",
                "model": "mock-v1",
                "auto_start": True,
            }
            grp_resp = client.post("/api/experiment-groups", json=group_payload)
            assert grp_resp.status_code == 201
            group_id = grp_resp.json()["group_id"]
            b_exp_id = grp_resp.json()["baseline"]["experiment"]["id"]

            for _ in range(40):
                r = client.get(f"/api/experiments/{b_exp_id}/runs").json()
                if r.get("total", 0) == 2 and all(x["status"] in {"completed", "failed"} for x in r.get("items", [])):
                    break
                time.sleep(0.05)

            # 1. Repetitions list export (JSONL)
            rep_export_jsonl = client.get(f"/api/experiments/{b_exp_id}/repetitions/exports/jsonl")
            assert rep_export_jsonl.status_code == 200
            assert "application/x-ndjson" in rep_export_jsonl.headers["content-type"]
            assert len(rep_export_jsonl.text.strip().split("\n")) >= 1

            # 2. Single repetition runs export (CSV)
            run_export_csv = client.get(f"/api/experiments/{b_exp_id}/repetitions/1/exports/csv")
            assert run_export_csv.status_code == 200
            assert "text/csv" in run_export_csv.headers["content-type"]
            csv_lines = run_export_csv.text.strip().split("\n")
            assert "run_id" in csv_lines[0]
            assert len(csv_lines) >= 3 # header + 2 runs

            # 3. Group export (JSONL + CSV)
            grp_export_jsonl = client.get(f"/api/experiment-groups/{group_id}/exports/jsonl")
            assert grp_export_jsonl.status_code == 200
            assert "application/x-ndjson" in grp_export_jsonl.headers["content-type"]

            grp_export_csv = client.get(f"/api/experiment-groups/{group_id}/exports/csv")
            assert grp_export_csv.status_code == 200
            assert "text/csv" in grp_export_csv.headers["content-type"]
            grp_csv_lines = grp_export_csv.text.strip().split("\n")
            assert "group_id" in grp_csv_lines[0]
            assert "condition" in grp_csv_lines[0]


def test_experiment_group_link_lifecycle_and_idempotency():
    """Verify linking separate baseline and egal experiments works in order, validates compatibility, and is idempotent."""
    with TemporaryDirectory() as tmpdir:
        snap_id = _make_sample_dataset(Path(tmpdir), count=2)

        with TestClient(app) as client:
            # 1. Create Baseline experiment first
            b_resp = client.post("/api/experiments", json={
                "name": "Manual Baseline",
                "dataset_snapshot_id": snap_id,
                "agent_id": "financial_news_analysis",
                "provider_id": "mock",
                "model": "mock-v1",
            })
            assert b_resp.status_code == 201
            b_exp = b_resp.json()

            # 2. Create EGAL experiment second
            e_resp = client.post("/api/experiments", json={
                "name": "Manual EGAL",
                "dataset_snapshot_id": snap_id,
                "agent_id": "financial_news_analysis_egal",
                "provider_id": "mock",
                "model": "mock-v1",
            })
            assert e_resp.status_code == 201
            e_exp = e_resp.json()

            # 3. Link them into a group
            link_resp = client.post("/api/experiment-groups/link", json={
                "group_name": "Linked Comparison Group",
                "experiment_ids": [b_exp["id"], e_exp["id"]],
            })
            assert link_resp.status_code == 200, link_resp.text
            grp_data = link_resp.json()
            group_id = grp_data["group_id"]
            assert grp_data["name"] == "Linked Comparison Group"
            assert grp_data["baseline"]["experiment"]["id"] == b_exp["id"]
            assert grp_data["egal"]["experiment"]["id"] == e_exp["id"]

            # 4. Idempotent re-link: repeating the link request on the same experiments should reuse the group
            relink_resp = client.post("/api/experiment-groups/link", json={
                "group_name": "Linked Comparison Group",
                "experiment_ids": [b_exp["id"], e_exp["id"]],
            })
            assert relink_resp.status_code == 200
            assert relink_resp.json()["group_id"] == group_id

            # Verify no duplicate groups in list
            all_groups = client.get("/api/experiment-groups").json()["items"]
            matching_groups = [g for g in all_groups if g["id"] == group_id]
            assert len(matching_groups) == 1


def test_experiment_group_link_validation_and_backward_compatibility():
    """Verify validation errors for missing/invalid required fields and backward compatibility aliases."""
    with TemporaryDirectory() as tmpdir:
        snap_id = _make_sample_dataset(Path(tmpdir), count=2)

        with TestClient(app) as client:
            b_exp = client.post("/api/experiments", json={
                "name": "B1",
                "dataset_snapshot_id": snap_id,
                "agent_id": "financial_news_analysis",
                "provider_id": "mock",
                "model": "mock-v1",
            }).json()

            e_exp = client.post("/api/experiments", json={
                "name": "E1",
                "dataset_snapshot_id": snap_id,
                "agent_id": "financial_news_analysis_egal",
                "provider_id": "mock",
                "model": "mock-v1",
            }).json()

            # Test missing experiment_ids (only 1 provided) -> 422
            resp1 = client.post("/api/experiment-groups/link", json={
                "group_name": "Incomplete Link",
                "experiment_ids": [b_exp["id"]],
            })
            assert resp1.status_code == 422
            err1 = resp1.json()
            assert "error" in err1 or "detail" in err1

            # Test empty group_name -> 422
            resp2 = client.post("/api/experiment-groups/link", json={
                "group_name": "",
                "experiment_ids": [b_exp["id"], e_exp["id"]],
            })
            assert resp2.status_code == 422

            # Test backward compatibility: baseline_experiment_id and egal_experiment_id
            resp3 = client.post("/api/experiment-groups/link", json={
                "group_name": "Compat Group",
                "baseline_experiment_id": b_exp["id"],
                "egal_experiment_id": e_exp["id"],
            })
            assert resp3.status_code == 200
            assert resp3.json()["name"] == "Compat Group"
