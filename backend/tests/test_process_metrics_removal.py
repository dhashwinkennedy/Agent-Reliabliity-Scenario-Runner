import sqlite3
from pathlib import Path
import json

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.api.v1.routes import router
from app.database.base import Base
from app.models.entities import Dataset, DatasetSnapshot, Experiment, Run, Evaluation
from app.services.evaluation import evaluate_experiment

client = TestClient(app)


def test_process_metrics_routes_are_completely_absent():
    """Verify that none of the removed process metrics endpoints exist in the registered routes."""
    router_paths = [getattr(r, "path", "") for r in router.routes]

    # Assert no route paths contain process metrics
    removed_path_substrings = [
        "/process-evaluations",
        "/process-metrics",
        "/process-events",
        "/process-expectations",
    ]
    for sub in removed_path_substrings:
        matching = [p for p in router_paths if sub in p]
        assert not matching, f"Found unexpected process metrics routes: {matching}"

    # Specifically test that removed process endpoints return 404 or 405/422
    assert client.get("/api/experiments/exp-123/process-evaluations").status_code in (404, 405)
    assert client.get("/api/experiments/exp-123/process-evaluations/eval-123").status_code == 404
    assert client.get("/api/experiments/exp-123/process-metrics").status_code in (404, 405)
    assert client.post("/api/runs/run-123/process-events", json={}).status_code == 404
    assert client.get("/api/runs/run-123/process-events").status_code == 404
    assert client.post("/api/process-expectations", json={}).status_code == 404
    assert client.get("/api/process-expectations").status_code == 404
    assert client.get("/api/process-expectations/scenario-1").status_code == 404
    # POST /api/experiments/{id}/process-evaluations must not execute any process logic
    # and either returns 404 or 422 (action validation error since action is not pause/resume/stop)
    post_res = client.post("/api/experiments/exp-123/process-evaluations", json={})
    assert post_res.status_code in (404, 422)


def test_execution_events_and_outcome_evaluation_endpoints_preserved():
    """Verify that experiment execution events and all outcome evaluation endpoints are preserved."""
    router_paths = [getattr(r, "path", "") for r in router.routes]

    assert "/experiments/{experiment_id}/events" in router_paths
    assert "/experiments/{experiment_id}/evaluations" in router_paths
    assert "/experiments/{experiment_id}/evaluations/{evaluation_id}" in router_paths
    assert "/evaluations" in router_paths


def test_process_tables_absent_from_database_models_and_sqlite():
    """Verify that process metrics tables are not in SQLAlchemy models or SQLite master."""
    # Check SQLAlchemy metadata
    forbidden_tables = {
        "run_process_evaluations",
        "process_events",
        "process_evaluations",
        "process_expectations",
    }
    model_tables = set(Base.metadata.tables.keys())
    intersection = model_tables.intersection(forbidden_tables)
    assert not intersection, f"Found forbidden process tables in Base.metadata: {intersection}"

    # Check live platform.db
    db_path = Path(__file__).parent.parent / "platform.db"
    if db_path.exists():
        con = sqlite3.connect(str(db_path))
        cursor = con.cursor()
        live_tables = {r[0] for r in cursor.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()}
        con.close()
        live_intersection = live_tables.intersection(forbidden_tables)
        assert not live_intersection, f"Found forbidden process tables in platform.db: {live_intersection}"


def test_outcome_evaluation_metrics_are_all_preserved_and_functional(tmp_path):
    """Verify that all six outcome metrics (5 in metrics dictionary + Run Coverage in manifest) are preserved."""
    snapshot_path = tmp_path / "scenario.jsonl"
    record_data = {
        "record_schema_version": "1.0",
        "scenario_id": "NORM-1",
        "category": "normal",
        "input": {
            "schema_version": "1.0",
            "scenario_id": "NORM-1",
            "ticker": "AAPL",
            "company_name": "Apple",
            "task": "Analyze.",
            "retrieval_mode": "provided_evidence",
            "search_query": None,
            "evidence": [
                {"evidence_id": "E1", "type": "news", "title": "T", "content": "C", "source_name": "S", "url": "https://example.com"}
            ]
        },
        "ground_truth": {
            "annotation_version": "1.0",
            "expected_task_completion": True,
            "supported_facts": [{"text": "Revenue grew", "evidence_ids": ["E1"]}],
        },
        "metadata": {"source_mode": "test"}
    }
    snapshot_path.write_text(json.dumps(record_data) + "\n", encoding="utf-8")

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    try:
        dataset = Dataset(id="ds1", display_name="D1", original_filename="d.jsonl", format="jsonl", size_bytes=100, fingerprint="f"*64, storage_path=str(snapshot_path))
        snap = DatasetSnapshot(id="snap1", dataset_id="ds1", fingerprint="f"*64, storage_path=str(snapshot_path))
        exp = Experiment(id="exp1", name="Exp 1", dataset_snapshot_id="snap1", agent_id="financial_news_analysis", provider_id="mock", input_mapping={}, status="completed")
        run = Run(
            id="run1",
            experiment_id="exp1",
            record_index=0,
            status="completed",
            normalized_output={
                "schema_version": "1.0",
                "scenario_id": "NORM-1",
                "ticker": "AAPL",
                "sentiment": "positive",
                "price_impact": "positive",
                "recommendation": "BUY",
                "confidence": 0.9,
                "forecast_pct": None,
                "forecast_horizon": "unspecified",
                "reasoning": [{"text": "Revenue grew", "evidence_ids": ["E1"]}],
                "key_factors": [],
                "risk_factors": [],
                "missing_information": [],
                "source_ids_used": ["E1"]
            }
        )
        db.add_all([dataset, snap, exp, run])
        db.commit()

        eval_obj = evaluate_experiment(db, exp)
        metrics = eval_obj.metrics

        # The 5 core research outcome metrics in metrics dictionary:
        required_outcome_metrics = [
            "task_completion_rate",
            "unsupported_action_rate",
            "recovery_rate",
            "consistency_rate",
            "false_success_rate",
        ]

        for metric in required_outcome_metrics:
            assert metric in metrics, f"Required outcome metric '{metric}' missing from evaluation output"
            assert "percentage" in metrics[metric], f"Metric '{metric}' missing percentage field"
            assert "numerator" in metrics[metric], f"Metric '{metric}' missing numerator field"
            assert "denominator" in metrics[metric], f"Metric '{metric}' missing denominator field"

        # The 6th outcome metric: Run Coverage (data completeness indicator)
        manifest = eval_obj.manifest
        assert "coverage_percentage" in manifest, "Coverage percentage missing from evaluation manifest"
        assert "completed_run_count" in manifest, "completed_run_count missing from evaluation manifest"
        assert "expected_run_count" in manifest, "expected_run_count missing from evaluation manifest"
        assert manifest["completed_run_count"] == 1
        assert manifest["expected_run_count"] == 1
        assert manifest["coverage_percentage"] == 100.0

        # Manifest metadata checks
        assert manifest["evaluation_status"] in ("COMPLETED", "INCOMPLETE")
        assert eval_obj.metric_definition_version == "research-metrics-v1"
        assert metrics["task_completion_rate"]["metric_version"] == "research-metrics-v1"
    finally:
        db.close()
        engine.dispose()
