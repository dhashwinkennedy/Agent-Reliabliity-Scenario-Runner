import json
from pathlib import Path
from tempfile import TemporaryDirectory
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database.base import Base
from app.database.session import get_db
from app.main import app
from app.models.entities import (
    Dataset,
    DatasetSnapshot,
    Experiment,
    Run,
    Evaluation,
    RunEvaluation,
    ProviderConfiguration,
)
from app.services.evaluation import evaluate_experiment, EVALUATION_SCHEMA_VERSION, METRIC_DEFINITION_VERSION


def _make_record(scenario_id: str, category: str, truth: dict | None = None) -> dict:
    return {
        "record_schema_version": "1.0",
        "scenario_id": scenario_id,
        "category": category,
        "input": {
            "schema_version": "1.0",
            "scenario_id": scenario_id,
            "ticker": "SYN",
            "company_name": "Synthetic Corp",
            "task": "Analyze news.",
            "retrieval_mode": "provided_evidence",
            "search_query": None,
            "evidence": [
                {
                    "evidence_id": "E1",
                    "type": "news",
                    "title": "Headline",
                    "content": "Content text here.",
                    "source_name": "Source",
                    "url": "https://example.test",
                }
            ],
        },
        "ground_truth": truth
        or {
            "annotation_version": "1.0",
            "expected_task_completion": True,
            "supported_facts": [{"text": "Content text here.", "evidence_ids": ["E1"]}],
        },
        "metadata": {"source_mode": "test"},
    }


def _make_baseline_output(scenario_id: str, rec: str = "HOLD", text: str = "Content text here.") -> dict:
    return {
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "ticker": "SYN",
        "sentiment": "neutral",
        "price_impact": "uncertain",
        "recommendation": rec,
        "confidence": 0.5,
        "forecast_pct": None,
        "forecast_horizon": "unspecified",
        "reasoning": [{"text": text, "evidence_ids": ["E1"]}],
        "key_factors": [],
        "risk_factors": [],
        "missing_information": ["Need more data"],
        "source_ids_used": ["E1"],
    }


def _make_egal_output(
    scenario_id: str,
    rec: str = "ABSTAIN",
    text: str = "Content text here.",
    correction_executed: bool = True,
    evidence_status: str = "insufficient",
) -> dict:
    return {
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "ticker": "SYN",
        "sentiment": "insufficient_evidence",
        "price_impact": "uncertain",
        "recommendation": rec,
        "confidence": 0.2,
        "forecast_pct": None,
        "forecast_horizon": "unspecified",
        "reasoning": [{"text": text, "evidence_ids": ["E1"]}],
        "key_factors": [],
        "risk_factors": [],
        "missing_information": ["Missing audited financials"],
        "source_ids_used": ["E1"],
        "abstention": {
            "status": "abstained" if rec == "ABSTAIN" else "not_abstained",
            "reason": "Unverified claims prevent directional action",
        },
        "audit": {
            "correction": {
                "executed": correction_executed,
                "strategy": "downgrade_to_abstain" if rec == "ABSTAIN" else "none",
            }
        },
        "final_evidence_sufficiency": {
            "schema_version": "1.0",
            "status": evidence_status,
            "material_unsupported_claim_ids": [],
            "material_contradiction_ids": [],
            "critical_missing_information": [],
            "recommendation_adequately_supported": rec != "ABSTAIN",
            "correction_required": correction_executed,
            "reason": "Diagnostic evaluation",
        },
        "final_claim_validation": {
            "schema_version": "1.0",
            "assessments": [],
        },
    }


@pytest.fixture
def setup_env():
    with TemporaryDirectory() as temp_dir:
        folder = Path(temp_dir)
        db_path = folder / "test_analysis.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)
        TestingSessionLocal = sessionmaker(bind=engine)

        def override_get_db():
            db = TestingSessionLocal()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db

        with TestClient(app) as client:
            yield {
                "folder": folder,
                "engine": engine,
                "Session": TestingSessionLocal,
                "client": client,
            }

        app.dependency_overrides.clear()
        engine.dispose()


def test_01_empty_dataset_analysis(setup_env):
    """Test 1: Empty dataset analysis returns insufficient_data, 0 coverage, unscored metrics."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    snap_file = folder / "empty.jsonl"
    snap_file.write_text("", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-empty", display_name="Empty DS", original_filename="empty.jsonl", format="jsonl", size_bytes=0, fingerprint="f"*64, storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-empty", dataset_id="ds-empty", fingerprint="f"*64, storage_path=str(snap_file))
    db.add_all([ds, snap])
    db.commit()
    db.close()

    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-empty"})
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["dataset"]["total_scenarios"] == 0
    assert data["coverage"]["expected_runs"] == 0
    assert data["coverage"]["completed_runs"] == 0
    assert data["coverage"]["status"] == "insufficient_data"
    assert data["coverage"]["is_preliminary"] is True
    assert data["model_comparison"] == []
    assert data["baseline_vs_egal"]["available"] is False
    assert data["egal_analysis"]["available"] is False
    assert data["charts"]["chart_1_primary_metrics"]["available"] is False


def test_02_one_baseline_run(setup_env):
    """Test 2: One baseline run clearly marks preliminary/partial analysis."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    scenarios = [_make_record("NORMAL-001", "normal")]
    snap_file = folder / "snap1.jsonl"
    snap_file.write_text("\n".join(json.dumps(s) for s in scenarios) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-1", display_name="DS 1", original_filename="snap1.jsonl", format="jsonl", size_bytes=100, fingerprint="1"*64, storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-1", dataset_id="ds-1", fingerprint="1"*64, storage_path=str(snap_file))
    exp = Experiment(id="exp-b1", name="Exp Baseline 1", dataset_snapshot_id="snap-1", agent_id="financial_news_analysis", provider_id="prov-openai", agent_configuration_snapshot={"model_override": "gpt-4o"}, status="completed")
    run = Run(id="run-b1", experiment_id="exp-b1", record_index=0, status="completed", normalized_output=_make_baseline_output("NORMAL-001", rec="BUY"))
    db.add_all([ds, snap, exp, run])
    db.commit()

    evaluate_experiment(db, exp)
    db.close()

    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-1"})
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["coverage"]["completed_runs"] == 1
    assert data["coverage"]["expected_runs"] == 1
    assert data["summary"]["completed_runs"] == 1
    assert len(data["model_comparison"]) == 1
    mc = data["model_comparison"][0]
    assert mc["model"] == "gpt-4o"
    assert mc["agent"] == "financial_news_analysis"
    assert mc["condition"] == "baseline"
    assert mc["task_completion_rate"] == 100.0

    # Recommendation distribution
    assert len(data["recommendation_distribution"]) == 1
    rd = data["recommendation_distribution"][0]
    assert rd["buy"] == 1
    assert rd["hold"] == 0
    assert rd["abstain"] == 0
    assert data["egal_analysis"]["available"] is False


def test_03_one_egal_run(setup_env):
    """Test 3: One EGAL run verifies EGAL diagnostics and ABSTAIN recommendation."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    scenarios = [_make_record("AMBIGUOUS-001", "ambiguous")]
    snap_file = folder / "snap_egal.jsonl"
    snap_file.write_text("\n".join(json.dumps(s) for s in scenarios) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-e", display_name="DS EGAL", original_filename="snap_egal.jsonl", format="jsonl", size_bytes=100, fingerprint="e"*64, storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-e", dataset_id="ds-e", fingerprint="e"*64, storage_path=str(snap_file))
    exp = Experiment(id="exp-e1", name="Exp EGAL 1", dataset_snapshot_id="snap-e", agent_id="financial_news_analysis_egal", provider_id="prov-openai", agent_configuration_snapshot={"model_override": "gpt-4o"}, status="completed")
    run = Run(id="run-e1", experiment_id="exp-e1", record_index=0, status="completed", normalized_output=_make_egal_output("AMBIGUOUS-001", rec="ABSTAIN", correction_executed=True, evidence_status="insufficient"))
    db.add_all([ds, snap, exp, run])
    db.commit()

    evaluate_experiment(db, exp)
    db.close()

    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-e"})
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["egal_analysis"]["available"] is True
    assert data["egal_analysis"]["abstain_count"] == 1
    assert data["egal_analysis"]["abstain_rate"] == 100.0
    assert data["egal_analysis"]["correction_executed_count"] == 1
    assert data["egal_analysis"]["evidence_insufficient_count"] == 1

    rd = data["recommendation_distribution"][0]
    assert rd["abstain"] == 1
    assert rd["hold"] == 0
    assert rd["buy"] == 0


def test_04_multiple_models(setup_env):
    """Test 4: Multiple models evaluated on the same dataset snapshot."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    scenarios = [_make_record("NORMAL-001", "normal")]
    snap_file = folder / "snap_multi.jsonl"
    snap_file.write_text("\n".join(json.dumps(s) for s in scenarios) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-m", display_name="DS Multi", original_filename="snap_multi.jsonl", format="jsonl", size_bytes=100, fingerprint="m"*64, storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-m", dataset_id="ds-m", fingerprint="m"*64, storage_path=str(snap_file))

    exp_a = Experiment(id="exp-a", name="Exp Model A", dataset_snapshot_id="snap-m", agent_id="financial_news_analysis", provider_id="provider-1", agent_configuration_snapshot={"model_override": "model-a"}, status="completed")
    run_a = Run(id="run-a", experiment_id="exp-a", record_index=0, status="completed", normalized_output=_make_baseline_output("NORMAL-001", rec="BUY"))

    exp_b = Experiment(id="exp-b", name="Exp Model B", dataset_snapshot_id="snap-m", agent_id="financial_news_analysis", provider_id="provider-1", agent_configuration_snapshot={"model_override": "model-b"}, status="completed")
    run_b = Run(id="run-b", experiment_id="exp-b", record_index=0, status="completed", normalized_output=_make_baseline_output("NORMAL-001", rec="HOLD"))

    db.add_all([ds, snap, exp_a, run_a, exp_b, run_b])
    db.commit()

    evaluate_experiment(db, exp_a)
    evaluate_experiment(db, exp_b)
    db.close()

    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-m"})
    assert res.status_code == 200, res.text
    data = res.json()

    assert data["summary"]["total_models"] == 2
    assert len(data["model_comparison"]) == 2
    models = {m["model"] for m in data["model_comparison"]}
    assert models == {"model-a", "model-b"}

    # Test filtering by model_name
    res_a = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-m", "model_name": "model-a"})
    assert res_a.status_code == 200
    data_a = res_a.json()
    assert len(data_a["model_comparison"]) == 1
    assert data_a["model_comparison"][0]["model"] == "model-a"


def test_05_baseline_vs_egal_comparison(setup_env):
    """Test 5: Baseline vs EGAL comparison computes directional metric deltas correctly."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    scenarios = [
        _make_record("NORMAL-001", "normal"),
        _make_record("AMBIGUOUS-001", "ambiguous", {
            "annotation_version": "1.0",
            "unsupported_claims": [{"text": "Unsupported", "evidence_ids": ["E1"]}],
        }),
    ]
    snap_file = folder / "snap_comp.jsonl"
    snap_file.write_text("\n".join(json.dumps(s) for s in scenarios) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-c", display_name="DS Comp", original_filename="snap_comp.jsonl", format="jsonl", size_bytes=100, fingerprint="c"*64, storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-c", dataset_id="ds-c", fingerprint="c"*64, storage_path=str(snap_file))

    # Baseline commits an unsupported action on AMBIGUOUS-001 by recommending BUY
    exp_base = Experiment(id="exp-base", name="Base", dataset_snapshot_id="snap-c", agent_id="financial_news_analysis", provider_id="prov-1", agent_configuration_snapshot={"model_override": "gpt-4"}, status="completed")
    run_b1 = Run(id="run-b1", experiment_id="exp-base", record_index=0, status="completed", normalized_output=_make_baseline_output("NORMAL-001", rec="BUY"))
    run_b2 = Run(id="run-b2", experiment_id="exp-base", record_index=1, status="completed", normalized_output=_make_baseline_output("AMBIGUOUS-001", rec="BUY", text="Unsupported"))

    # EGAL abstains on AMBIGUOUS-001
    exp_egal = Experiment(id="exp-egal", name="EGAL", dataset_snapshot_id="snap-c", agent_id="financial_news_analysis_egal", provider_id="prov-1", agent_configuration_snapshot={"model_override": "gpt-4"}, status="completed")
    run_e1 = Run(id="run-e1", experiment_id="exp-egal", record_index=0, status="completed", normalized_output=_make_egal_output("NORMAL-001", rec="BUY"))
    run_e2 = Run(id="run-e2", experiment_id="exp-egal", record_index=1, status="completed", normalized_output=_make_egal_output("AMBIGUOUS-001", rec="ABSTAIN"))

    db.add_all([ds, snap, exp_base, run_b1, run_b2, exp_egal, run_e1, run_e2])
    db.commit()

    evaluate_experiment(db, exp_base)
    evaluate_experiment(db, exp_egal)
    db.close()

    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-c"})
    assert res.status_code == 200, res.text
    data = res.json()

    b_vs_e = data["baseline_vs_egal"]
    assert b_vs_e["available"] is True
    assert len(b_vs_e["comparisons"]) == 1
    comp = b_vs_e["comparisons"][0]
    assert comp["model"] == "gpt-4"
    assert comp["provider"] == "prov-1"

    deltas = comp["delta"]
    # Baseline unsupported action was 100%, EGAL unsupported action was 0%
    # Delta = 0.0 - 100.0 = -100.0. Since lower is better, this is an improvement!
    assert deltas["unsupported_action_rate"]["value"] == -100.0
    assert deltas["unsupported_action_rate"]["direction"] == "improved"
    assert deltas["unsupported_action_rate"]["interpretation"] == "lower_is_better"

    # Task completion: both were 100%, delta = 0.0, unchanged
    assert deltas["task_completion_rate"]["value"] == 0.0
    assert deltas["task_completion_rate"]["direction"] == "unchanged"


def test_06_partial_90_run_experiment(setup_env):
    """Test 6: Partial 90-run experiment reports partial coverage and is_preliminary=True."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    snap_file = folder / "snap_90.jsonl"
    snap_file.write_text("\n".join(json.dumps(_make_record(f"SCENARIO-{i}", "normal")) for i in range(18)) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-90", display_name="DS 90", original_filename="snap_90.jsonl", format="jsonl", size_bytes=100, fingerprint="9"*64, storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-90", dataset_id="ds-90", fingerprint="9"*64, storage_path=str(snap_file))
    exp = Experiment(id="exp-p90", name="Exp Partial 90", dataset_snapshot_id="snap-90", agent_id="financial_news_analysis", provider_id="prov-1", agent_configuration_snapshot={"model_override": "gpt-4"}, status="running")

    # 88 completed, 2 failed = 90 total
    runs = [
        Run(id=f"run-{i}", experiment_id="exp-p90", record_index=i % 18, status="completed", normalized_output=_make_baseline_output(f"SCENARIO-{i % 18}"))
        for i in range(88)
    ]
    runs.append(Run(id="run-fail-1", experiment_id="exp-p90", record_index=0, status="failed", error={"msg": "timeout"}))
    runs.append(Run(id="run-fail-2", experiment_id="exp-p90", record_index=1, status="failed", error={"msg": "timeout"}))

    db.add_all([ds, snap, exp] + runs)
    db.commit()

    # Create Evaluation with expected_run_count=90
    ev = Evaluation(
        id="eval-p90",
        experiment_id="exp-p90",
        dataset_snapshot_id="snap-90",
        dataset_fingerprint="9"*64,
        evaluation_schema_version=EVALUATION_SCHEMA_VERSION,
        metric_definition_version=METRIC_DEFINITION_VERSION,
        status="completed",
        expected_run_count=90,
        metrics={"task_completion_rate": {"percentage": 95.0}},
    )
    db.add(ev)
    db.commit()
    db.close()

    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-90"})
    assert res.status_code == 200, res.text
    data = res.json()

    cov = data["coverage"]
    assert cov["expected_runs"] == 90
    assert cov["completed_runs"] == 88
    assert cov["failed_runs"] == 2
    assert cov["coverage_percentage"] == 97.78
    assert cov["status"] == "partial"
    assert cov["is_preliminary"] is True


def test_07_complete_90_run_experiment(setup_env):
    """Test 7: Complete 90-run experiment reports complete coverage and is_preliminary=False."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    snap_file = folder / "snap_c90.jsonl"
    snap_file.write_text("\n".join(json.dumps(_make_record(f"SCENARIO-{i}", "normal")) for i in range(18)) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-c90", display_name="DS C90", original_filename="snap_c90.jsonl", format="jsonl", size_bytes=100, fingerprint="c9"*32, storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-c90", dataset_id="ds-c90", fingerprint="c9"*32, storage_path=str(snap_file))
    exp = Experiment(id="exp-c90", name="Exp Complete 90", dataset_snapshot_id="snap-c90", agent_id="financial_news_analysis", provider_id="prov-1", agent_configuration_snapshot={"model_override": "gpt-4"}, status="completed")

    runs = [
        Run(id=f"run-c-{i}", experiment_id="exp-c90", record_index=i % 18, status="completed", normalized_output=_make_baseline_output(f"SCENARIO-{i % 18}"))
        for i in range(90)
    ]
    db.add_all([ds, snap, exp] + runs)
    db.commit()

    ev = Evaluation(
        id="eval-c90",
        experiment_id="exp-c90",
        dataset_snapshot_id="snap-c90",
        dataset_fingerprint="c9"*32,
        evaluation_schema_version=EVALUATION_SCHEMA_VERSION,
        metric_definition_version=METRIC_DEFINITION_VERSION,
        status="completed",
        expected_run_count=90,
        metrics={"task_completion_rate": {"percentage": 100.0}},
    )
    db.add(ev)
    db.commit()
    db.close()

    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-c90"})
    assert res.status_code == 200, res.text
    data = res.json()

    cov = data["coverage"]
    assert cov["expected_runs"] == 90
    assert cov["completed_runs"] == 90
    assert cov["failed_runs"] == 0
    assert cov["coverage_percentage"] == 100.0
    assert cov["status"] == "complete"
    assert cov["is_preliminary"] is False


def test_08_failed_runs_never_treated_as_successful(setup_env):
    """Test 8: Failed runs are counted under failed_runs and never masked as successful."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    snap_file = folder / "snap_fail.jsonl"
    snap_file.write_text(json.dumps(_make_record("NORMAL-001", "normal")) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-f", display_name="DS Fail", original_filename="snap_fail.jsonl", format="jsonl", size_bytes=100, fingerprint="f"*64, storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-f", dataset_id="ds-f", fingerprint="f"*64, storage_path=str(snap_file))
    exp = Experiment(id="exp-f", name="Exp Fail", dataset_snapshot_id="snap-f", agent_id="financial_news_analysis", provider_id="prov-1", status="completed")
    run = Run(id="run-fail", experiment_id="exp-f", record_index=0, status="failed", error={"code": "TIMEOUT"})
    db.add_all([ds, snap, exp, run])
    db.commit()

    evaluate_experiment(db, exp)
    db.close()

    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-f"})
    assert res.status_code == 200
    data = res.json()

    assert data["coverage"]["failed_runs"] == 1
    assert data["coverage"]["completed_runs"] == 0
    assert data["coverage"]["status"] == "insufficient_data"


def test_09_missing_evaluation_handled_gracefully(setup_env):
    """Test 9: Missing evaluation does not crash and indicates un-evaluated state."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    snap_file = folder / "snap_ne.jsonl"
    snap_file.write_text(json.dumps(_make_record("NORMAL-001", "normal")) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-ne", display_name="DS NE", original_filename="snap_ne.jsonl", format="jsonl", size_bytes=100, fingerprint="ne"*32, storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-ne", dataset_id="ds-ne", fingerprint="ne"*32, storage_path=str(snap_file))
    exp = Experiment(id="exp-ne", name="Exp No Eval", dataset_snapshot_id="snap-ne", agent_id="financial_news_analysis", provider_id="prov-1", status="completed")
    run = Run(id="run-ne", experiment_id="exp-ne", record_index=0, status="completed", normalized_output=_make_baseline_output("NORMAL-001"))
    db.add_all([ds, snap, exp, run])
    db.commit()
    db.close()

    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-ne"})
    assert res.status_code == 200, res.text
    data = res.json()

    mc = data["model_comparison"][0]
    assert mc["has_evaluation"] is False
    assert mc["task_completion_rate"] is None
    assert data["coverage"]["completed_runs"] == 1


def test_10_scenario_breakdown(setup_env):
    """Test 10: Scenario breakdown table exposes all scenarios and diagnostic columns."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    scenarios = [
        _make_record("NORMAL-001", "normal"),
        _make_record("AMBIGUOUS-001", "ambiguous"),
        _make_record("FAILURE-001", "failure", {"annotation_version": "1.0", "recovery": {"recoverable": True}}),
    ]
    snap_file = folder / "snap_sc.jsonl"
    snap_file.write_text("\n".join(json.dumps(s) for s in scenarios) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-sc", display_name="DS Sc", original_filename="snap_sc.jsonl", format="jsonl", size_bytes=100, fingerprint="sc"*32, storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-sc", dataset_id="ds-sc", fingerprint="sc"*32, storage_path=str(snap_file))
    exp = Experiment(id="exp-sc", name="Exp Sc", dataset_snapshot_id="snap-sc", agent_id="financial_news_analysis", provider_id="prov-1", status="completed")

    runs = [
        Run(id="run-sc-1", experiment_id="exp-sc", record_index=0, status="completed", normalized_output=_make_baseline_output("NORMAL-001", rec="BUY")),
        Run(id="run-sc-2", experiment_id="exp-sc", record_index=1, status="completed", normalized_output=_make_baseline_output("AMBIGUOUS-001", rec="HOLD")),
        Run(id="run-sc-3", experiment_id="exp-sc", record_index=2, status="completed", normalized_output=_make_baseline_output("FAILURE-001", rec="HOLD")),
    ]
    db.add_all([ds, snap, exp] + runs)
    db.commit()

    evaluate_experiment(db, exp)
    db.close()

    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-sc"})
    assert res.status_code == 200
    data = res.json()

    sb = data["scenario_breakdown"]
    assert len(sb) == 3
    sc_map = {s["scenario_id"]: s for s in sb}

    assert sc_map["NORMAL-001"]["category"] == "normal"
    assert sc_map["NORMAL-001"]["task_completion"]["status"] == "pass"

    assert sc_map["AMBIGUOUS-001"]["category"] == "ambiguous"
    assert sc_map["AMBIGUOUS-001"]["unsupported_action"]["status"] == "assessed"

    assert sc_map["FAILURE-001"]["category"] == "failure"
    assert sc_map["FAILURE-001"]["recovery"]["status"] == "recovered"


def test_11_recommendation_distribution(setup_env):
    """Test 11: Recommendation distribution exposes BUY/HOLD/SELL/ABSTAIN with strict typing."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    scenarios = [_make_record("NORMAL-001", "normal")]
    snap_file = folder / "snap_rd.jsonl"
    snap_file.write_text(json.dumps(scenarios[0]) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-rd", display_name="DS RD", original_filename="snap_rd.jsonl", format="jsonl", size_bytes=100, fingerprint="rd"*32, storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-rd", dataset_id="ds-rd", fingerprint="rd"*32, storage_path=str(snap_file))

    # Baseline has HOLD and BUY
    exp_b = Experiment(id="exp-b-rd", name="Exp B", dataset_snapshot_id="snap-rd", agent_id="financial_news_analysis", provider_id="prov-1", status="completed")
    r1 = Run(id="r1", experiment_id="exp-b-rd", record_index=0, status="completed", normalized_output=_make_baseline_output("NORMAL-001", rec="HOLD"))
    r2 = Run(id="r2", experiment_id="exp-b-rd", record_index=0, status="completed", normalized_output=_make_baseline_output("NORMAL-001", rec="BUY"))

    # EGAL has ABSTAIN
    exp_e = Experiment(id="exp-e-rd", name="Exp E", dataset_snapshot_id="snap-rd", agent_id="financial_news_analysis_egal", provider_id="prov-1", status="completed")
    r3 = Run(id="r3", experiment_id="exp-e-rd", record_index=0, status="completed", normalized_output=_make_egal_output("NORMAL-001", rec="ABSTAIN"))

    db.add_all([ds, snap, exp_b, r1, r2, exp_e, r3])
    db.commit()
    db.close()

    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-rd"})
    assert res.status_code == 200
    data = res.json()

    rd = data["recommendation_distribution"]
    assert len(rd) == 2
    b_dist = next(r for r in rd if r["condition"] == "baseline")
    e_dist = next(r for r in rd if r["condition"] == "egal")

    assert b_dist["buy"] == 1
    assert b_dist["hold"] == 1
    assert b_dist["abstain"] == 0  # Baseline must never have abstain

    assert e_dist["abstain"] == 1
    assert e_dist["hold"] == 0  # HOLD is never reinterpreted as ABSTAIN


def test_12_egal_abstention_metrics(setup_env):
    """Test 12: EGAL diagnostics calculate audit corrections, evidence sufficiency, and claims."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    scenarios = [_make_record("AMBIGUOUS-001", "ambiguous", {
        "annotation_version": "1.0",
        "contradictions": [{"text": "Contradictory claim", "evidence_ids": ["E1"]}],
    })]
    snap_file = folder / "snap_egm.jsonl"
    snap_file.write_text(json.dumps(scenarios[0]) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-egm", display_name="DS EGM", original_filename="snap_egm.jsonl", format="jsonl", size_bytes=100, fingerprint="egm"*21 + "a", storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-egm", dataset_id="ds-egm", fingerprint="egm"*21 + "a", storage_path=str(snap_file))
    exp = Experiment(id="exp-egm", name="Exp EGM", dataset_snapshot_id="snap-egm", agent_id="financial_news_analysis_egal", provider_id="prov-1", status="completed")
    run = Run(id="run-egm", experiment_id="exp-egm", record_index=0, status="completed", normalized_output=_make_egal_output("AMBIGUOUS-001", rec="ABSTAIN", text="Contradictory claim", correction_executed=True, evidence_status="insufficient"))
    db.add_all([ds, snap, exp, run])
    db.commit()

    evaluate_experiment(db, exp)
    db.close()

    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-egm"})
    assert res.status_code == 200
    data = res.json()

    ea = data["egal_analysis"]
    assert ea["available"] is True
    assert ea["abstain_count"] == 1
    assert ea["correction_executed_count"] == 1
    assert ea["evidence_insufficient_count"] == 1
    assert ea["contradicted_claim_count"] == 1


def test_13_provider_model_separation(setup_env):
    """Test 13: Models with same name under different providers remain strictly separated."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    scenarios = [_make_record("NORMAL-001", "normal")]
    snap_file = folder / "snap_pms.jsonl"
    snap_file.write_text(json.dumps(scenarios[0]) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-pms", display_name="DS PMS", original_filename="snap_pms.jsonl", format="jsonl", size_bytes=100, fingerprint="pms"*21 + "a", storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-pms", dataset_id="ds-pms", fingerprint="pms"*21 + "a", storage_path=str(snap_file))

    # Provider A with model-x
    exp_a = Experiment(id="exp-pa", name="Exp PA", dataset_snapshot_id="snap-pms", agent_id="financial_news_analysis", provider_id="provider-a", agent_configuration_snapshot={"model_override": "model-x"}, status="completed")
    r_a = Run(id="r-pa", experiment_id="exp-pa", record_index=0, status="completed", normalized_output=_make_baseline_output("NORMAL-001"))

    # Provider B with model-x
    exp_b = Experiment(id="exp-pb", name="Exp PB", dataset_snapshot_id="snap-pms", agent_id="financial_news_analysis", provider_id="provider-b", agent_configuration_snapshot={"model_override": "model-x"}, status="completed")
    r_b = Run(id="r-pb", experiment_id="exp-pb", record_index=0, status="completed", normalized_output=_make_baseline_output("NORMAL-001"))

    db.add_all([ds, snap, exp_a, r_a, exp_b, r_b])
    db.commit()
    db.close()

    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-pms"})
    assert res.status_code == 200
    data = res.json()

    # Must be 2 separate models in comparison
    assert len(data["model_comparison"]) == 2
    providers = {m["provider"] for m in data["model_comparison"]}
    assert providers == {"provider-a", "provider-b"}


def test_14_dataset_snapshot_mismatch_protection(setup_env):
    """Test 14: Protects against evaluating experiments from an incompatible dataset snapshot."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    snap_file_1 = folder / "snap_1.jsonl"
    snap_file_1.write_text(json.dumps(_make_record("NORMAL-001", "normal")) + "\n", encoding="utf-8")
    snap_file_2 = folder / "snap_2.jsonl"
    snap_file_2.write_text(json.dumps(_make_record("NORMAL-002", "normal")) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-mm", display_name="DS MM", original_filename="snap_1.jsonl", format="jsonl", size_bytes=100, fingerprint="mm"*32, storage_path=str(snap_file_1))
    snap1 = DatasetSnapshot(id="snap-1", dataset_id="ds-mm", fingerprint="mm1"*21 + "a", storage_path=str(snap_file_1))
    snap2 = DatasetSnapshot(id="snap-2", dataset_id="ds-mm", fingerprint="mm2"*21 + "a", storage_path=str(snap_file_2))

    exp1 = Experiment(id="exp-on-snap2", name="Exp Snap2", dataset_snapshot_id="snap-2", agent_id="financial_news_analysis", provider_id="prov-1", status="completed")
    db.add_all([ds, snap1, snap2, exp1])
    db.commit()
    db.close()

    # Pass snapshot 1, but specify experiment that was run on snapshot 2
    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-1", "experiment_ids": ["exp-on-snap2"]})
    assert res.status_code == 400
    err = res.json()["error"]
    assert err["code"] == "DATASET_SNAPSHOT_MISMATCH"


def test_15_no_fabricated_metrics(setup_env):
    """Test 15: No fabricated metrics when denominators are zero or data is missing."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    # Only normal scenario, no failure or ambiguous
    scenarios = [_make_record("NORMAL-001", "normal")]
    snap_file = folder / "snap_nofab.jsonl"
    snap_file.write_text(json.dumps(scenarios[0]) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-nf", display_name="DS NF", original_filename="snap_nofab.jsonl", format="jsonl", size_bytes=100, fingerprint="nf"*32, storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-nf", dataset_id="ds-nf", fingerprint="nf"*32, storage_path=str(snap_file))
    exp = Experiment(id="exp-nf", name="Exp NF", dataset_snapshot_id="snap-nf", agent_id="financial_news_analysis", provider_id="prov-1", status="completed")
    run = Run(id="run-nf", experiment_id="exp-nf", record_index=0, status="completed", normalized_output=_make_baseline_output("NORMAL-001"))
    db.add_all([ds, snap, exp, run])
    db.commit()

    evaluate_experiment(db, exp)
    db.close()

    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-nf"})
    assert res.status_code == 200
    data = res.json()

    mc = data["model_comparison"][0]
    # Recovery rate had no failure scenarios, must be None, NOT 0.0 or 100.0
    assert mc["recovery_rate"] is None
    # Unsupported action had no ambiguous scenarios, must be None
    assert mc["unsupported_action_rate"] is None

    # Chart 5 (Recovery) should be available=False since no data exists
    assert data["charts"]["chart_5_recovery_rate"]["available"] is False


def test_16_correct_research_metrics_v1_usage(setup_env):
    """Test 16: Research metrics version is research-metrics-v1 in metadata and evaluations."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    scenarios = [_make_record("NORMAL-001", "normal")]
    snap_file = folder / "snap_v1.jsonl"
    snap_file.write_text(json.dumps(scenarios[0]) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-v1", display_name="DS V1", original_filename="snap_v1.jsonl", format="jsonl", size_bytes=100, fingerprint="v1"*32, storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-v1", dataset_id="ds-v1", fingerprint="v1"*32, storage_path=str(snap_file))
    exp = Experiment(id="exp-v1", name="Exp V1", dataset_snapshot_id="snap-v1", agent_id="financial_news_analysis", provider_id="prov-1", status="completed")
    run = Run(id="run-v1", experiment_id="exp-v1", record_index=0, status="completed", normalized_output=_make_baseline_output("NORMAL-001"))
    db.add_all([ds, snap, exp, run])
    db.commit()

    evaluate_experiment(db, exp)
    db.close()

    res = client.post("/api/analysis/report", json={"dataset_snapshot_id": "snap-v1"})
    assert res.status_code == 200
    data = res.json()

    assert data["research_metadata"]["metric_definition_version"] == "research-metrics-v1"
    assert data["primary_metrics"]["task_completion_rate"]["metric_version"] == "research-metrics-v1"


def test_17_analysis_options_endpoint(setup_env):
    """Test 17: GET /api/analysis/options returns selectable dimensions based on actual persisted data."""
    folder = setup_env["folder"]
    client = setup_env["client"]
    Session = setup_env["Session"]

    snap_file = folder / "snap_opt.jsonl"
    snap_file.write_text(json.dumps(_make_record("NORMAL-001", "normal")) + "\n", encoding="utf-8")

    db = Session()
    ds = Dataset(id="ds-opt", display_name="Options Dataset", original_filename="snap_opt.jsonl", format="jsonl", size_bytes=100, fingerprint="opt"*21 + "a", storage_path=str(snap_file))
    snap = DatasetSnapshot(id="snap-opt", dataset_id="ds-opt", fingerprint="opt"*21 + "a", storage_path=str(snap_file))
    prov = ProviderConfiguration(id="prov-opt", display_name="Custom Provider", provider_type="openai_compatible", base_url="https://api.openai.com/v1", model="gpt-4o-mini", timeout_seconds=30.0)
    exp = Experiment(id="exp-opt", name="Exp Opt", dataset_snapshot_id="snap-opt", agent_id="financial_news_analysis_egal", provider_id="prov-opt", status="completed")
    db.add_all([ds, snap, prov, exp])
    db.commit()
    db.close()

    res = client.get("/api/analysis/options")
    assert res.status_code == 200, res.text
    options = res.json()

    assert any(d["id"] == "ds-opt" for d in options["datasets"])
    assert any(s["id"] == "snap-opt" for s in options["dataset_snapshots"])
    assert any(p["id"] == "prov-opt" for p in options["providers"])
    assert "gpt-4o-mini" in options["models"]
    assert any(a["id"] == "financial_news_analysis_egal" for a in options["agents"])
    assert any(e["id"] == "exp-opt" for e in options["experiments"])
    assert "egal" in options["conditions"]
