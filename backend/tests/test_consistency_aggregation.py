"""Tests for Cross-Experiment Consistency Aggregation.
Verifies all 13 required test conditions:
1. Five compatible evaluations, with one record per repeatability scenario from each evaluation.
2. Fully consistent repetitions.
3. Differing normalized decisions.
4. Differing execution statuses.
5. Failed repetitions.
6. Missing repetition data.
7. Incompatible dataset fingerprints.
8. Incompatible metric definition versions.
9. Duplicate evaluation IDs.
10. Missing or inaccessible evaluations.
11. Correct aggregate numerator, denominator, percentage, and coverage.
12. No agent/provider calls during aggregation.
13. Historical individual evaluations remaining unchanged.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient
from app.database.base import Base
from app.models.entities import Evaluation, RunEvaluation, Experiment, DatasetSnapshot, ConsistencyAggregation
from app.services.consistency import aggregate_consistency, validate_evaluations_for_consistency, REPEATABILITY_IDS
from app.main import app

@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    try:
        yield session
    finally:
        session.close()

def _create_mock_eval_and_runs(db, eval_id, exp_id, snapshot_id="snap_1", fingerprint="fp_abc", metric_version="research-metrics-v1", overrides=None):
    overrides = overrides or {}
    ev = Evaluation(
        id=eval_id,
        experiment_id=exp_id,
        dataset_snapshot_id=snapshot_id,
        dataset_fingerprint=fingerprint,
        evaluation_schema_version="1.0",
        metric_definition_version=metric_version,
        status="completed",
        expected_run_count=18,
        metrics={},
        manifest={},
    )
    db.add(ev)
    db.commit()

    for sc in REPEATABILITY_IDS:
        cat = "normal" if "NORMAL" in sc else ("ambiguous" if "AMBIGUOUS" in sc else "failure")
        sc_overrides = overrides.get(sc, {})
        rev = RunEvaluation(
            id=f"rev_{eval_id}_{sc}",
            evaluation_id=eval_id,
            run_id=f"run_{exp_id}_{sc}",
            scenario_id=sc,
            category=cat,
            execution_status=sc_overrides.get("execution_status", "completed"),
            output_schema_valid=sc_overrides.get("output_schema_valid", True),
            task_completion={"status": sc_overrides.get("task_completion_status", "pass" if cat == "normal" else "not_applicable")},
            unsupported_action={"present": sc_overrides.get("unsupported_action_present", False if cat == "ambiguous" else None)},
            recovery={"status": sc_overrides.get("recovery_status", "recovered" if sc == "FAILURE-001" else "not_applicable")},
            decision_signature={
                "sentiment": sc_overrides.get("sentiment", "positive" if cat == "normal" else "neutral"),
                "price_impact": sc_overrides.get("price_impact", "positive" if cat == "normal" else "neutral"),
                "recommendation": sc_overrides.get("recommendation", "BUY" if cat == "normal" else "HOLD"),
                "forecast_present": sc_overrides.get("forecast_present", False),
                "forecast_horizon": sc_overrides.get("forecast_horizon", "short_term"),
            },
            exclusions=sc_overrides.get("exclusions", []),
        )
        db.add(rev)
    db.commit()
    return ev

def test_1_and_2_compatible_and_fully_consistent(test_db):
    """Test 1 & 2: Five compatible evaluations with fully consistent repetitions across all 6 scenarios."""
    eval_ids = []
    for i in range(1, 6):
        eid = f"eval_{i}"
        _create_mock_eval_and_runs(test_db, eid, f"exp_{i}")
        eval_ids.append(eid)
    
    agg = aggregate_consistency(test_db, eval_ids, persist=True)
    assert agg.aggregation_status == "complete"
    assert agg.assessable_group_count == 6
    assert agg.consistent_group_count == 6
    assert agg.excluded_group_count == 0
    assert agg.consistency_rate == 100.0
    assert agg.coverage == 100.0
    for sc_res in agg.repeatability_scenario_results:
        assert sc_res["is_consistent"] is True
        assert sc_res["status"] == "consistent"
        assert len(sc_res["differing_fields"]) == 0

def test_3_differing_normalized_decisions(test_db):
    """Test 3: Repetitions differing in normalized decision signature (e.g. recommendation)."""
    eval_ids = []
    for i in range(1, 6):
        eid = f"eval_{i}"
        # Eval 3 gives HOLD on NORMAL-001 while others give BUY
        overrides = {}
        if i == 3:
            overrides["NORMAL-001"] = {"recommendation": "HOLD"}
        _create_mock_eval_and_runs(test_db, eid, f"exp_{i}", overrides=overrides)
        eval_ids.append(eid)

    agg = aggregate_consistency(test_db, eval_ids, persist=False)
    normal_1 = next(s for s in agg.repeatability_scenario_results if s["scenario_id"] == "NORMAL-001")
    assert normal_1["is_consistent"] is False
    assert normal_1["status"] == "inconsistent"
    assert "recommendation" in normal_1["differing_fields"]
    assert normal_1["differing_fields"]["recommendation"] == ["BUY", "BUY", "HOLD", "BUY", "BUY"]
    assert agg.consistent_group_count == 5
    assert agg.assessable_group_count == 6
    assert agg.consistency_rate == round(5 / 6 * 100, 4)

def test_4_and_5_differing_execution_statuses_and_failed_repetitions(test_db):
    """Test 4 & 5: Failed repetitions are included in analysis and not counted as successful or consistent."""
    eval_ids = []
    for i in range(1, 6):
        eid = f"eval_{i}"
        overrides = {}
        if i == 5:
            # Run 5 on FAILURE-003 failed
            overrides["FAILURE-003"] = {
                "execution_status": "failed",
                "output_schema_valid": False,
                "task_completion_status": "fail",
                "recovery_status": "unscored",
                "sentiment": None,
                "recommendation": None,
            }
        _create_mock_eval_and_runs(test_db, eid, f"exp_{i}", overrides=overrides)
        eval_ids.append(eid)

    agg = aggregate_consistency(test_db, eval_ids, persist=False)
    f3 = next(s for s in agg.repeatability_scenario_results if s["scenario_id"] == "FAILURE-003")
    assert f3["is_consistent"] is False
    assert f3["is_assessable"] is True
    assert "execution_status" in f3["differing_fields"]
    assert f3["differing_fields"]["execution_status"] == ["completed", "completed", "completed", "completed", "failed"]

def test_6_missing_repetition_data(test_db):
    """Test 6: Missing repetition data causes not_assessable state for that group."""
    eval_ids = []
    for i in range(1, 6):
        eid = f"eval_{i}"
        _create_mock_eval_and_runs(test_db, eid, f"exp_{i}")
        eval_ids.append(eid)
    
    # Delete the run evaluation for eval_5 on AMBIGUOUS-001
    rev_to_del = test_db.query(RunEvaluation).filter_by(evaluation_id="eval_5", scenario_id="AMBIGUOUS-001").first()
    test_db.delete(rev_to_del)
    test_db.commit()

    agg = aggregate_consistency(test_db, eval_ids, persist=False)
    amb_1 = next(s for s in agg.repeatability_scenario_results if s["scenario_id"] == "AMBIGUOUS-001")
    assert amb_1["status"] == "not_assessable"
    assert amb_1["is_assessable"] is False
    assert agg.assessable_group_count == 5
    assert agg.excluded_group_count == 1
    assert agg.aggregation_status == "partial"
    assert agg.coverage == round(5 / 6 * 100, 4)

def test_7_incompatible_dataset_fingerprints(test_db):
    """Test 7: Incompatible dataset fingerprints across evaluations raise error."""
    _create_mock_eval_and_runs(test_db, "eval_1", "exp_1", fingerprint="fp_1")
    _create_mock_eval_and_runs(test_db, "eval_2", "exp_2", fingerprint="fp_2")
    with pytest.raises(ValueError, match="Incompatible dataset fingerprints"):
        aggregate_consistency(test_db, ["eval_1", "eval_2"])

def test_8_incompatible_metric_definition_versions(test_db):
    """Test 8: Incompatible metric definition versions raise error."""
    _create_mock_eval_and_runs(test_db, "eval_1", "exp_1", metric_version="research-metrics-v1")
    _create_mock_eval_and_runs(test_db, "eval_2", "exp_2", metric_version="research-metrics-v2")
    with pytest.raises(ValueError, match="Incompatible metric definition versions"):
        aggregate_consistency(test_db, ["eval_1", "eval_2"])

def test_9_duplicate_evaluation_ids(test_db):
    """Test 9: Duplicate evaluation IDs raise error."""
    _create_mock_eval_and_runs(test_db, "eval_1", "exp_1")
    with pytest.raises(ValueError, match="Duplicate evaluation IDs"):
        aggregate_consistency(test_db, ["eval_1", "eval_1"])

def test_10_missing_or_inaccessible_evaluations(test_db):
    """Test 10: Missing evaluation IDs raise error."""
    _create_mock_eval_and_runs(test_db, "eval_1", "exp_1")
    with pytest.raises(ValueError, match="not found or inaccessible"):
        aggregate_consistency(test_db, ["eval_1", "eval_nonexistent"])

def test_11_aggregate_metrics_calculations(test_db):
    """Test 11: Correct aggregate numerator, denominator, percentage, and coverage."""
    eval_ids = []
    # Make 2 scenarios consistent, 4 inconsistent
    for i in range(1, 6):
        eid = f"eval_{i}"
        overrides = {}
        if i % 2 == 0:
            overrides["NORMAL-001"] = {"recommendation": "HOLD"}
            overrides["AMBIGUOUS-001"] = {"unsupported_action_present": True}
            overrides["FAILURE-001"] = {"sentiment": "negative"}
            overrides["FAILURE-003"] = {"recommendation": "SELL"}
        _create_mock_eval_and_runs(test_db, eid, f"exp_{i}", overrides=overrides)
        eval_ids.append(eid)
    
    agg = aggregate_consistency(test_db, eval_ids, persist=True)
    assert agg.assessable_group_count == 6
    assert agg.consistent_group_count == 2 # NORMAL-004 and AMBIGUOUS-005 consistent
    assert agg.consistency_rate == round(2 / 6 * 100, 4)
    assert agg.coverage == 100.0

def test_12_no_agent_provider_calls(test_db, monkeypatch):
    """Test 12: No external agent or provider calls happen during aggregation."""
    # If any HTTP call or agent call were made, fail the test
    def fail_call(*args, **kwargs):
        raise AssertionError("External agent/provider call attempted during offline consistency aggregation!")
    
    monkeypatch.setattr("urllib.request.urlopen", fail_call, raising=False)
    
    eval_ids = []
    for i in range(1, 6):
        eid = f"eval_{i}"
        _create_mock_eval_and_runs(test_db, eid, f"exp_{i}")
        eval_ids.append(eid)
    
    agg = aggregate_consistency(test_db, eval_ids, persist=False)
    assert agg.consistent_group_count == 6

def test_13_historical_evaluations_unchanged(test_db):
    """Test 13: Historical individual evaluations and run evaluations remain strictly unchanged."""
    eval_ids = []
    for i in range(1, 6):
        eid = f"eval_{i}"
        _create_mock_eval_and_runs(test_db, eid, f"exp_{i}")
        eval_ids.append(eid)
    
    # Capture snapshot of existing eval records
    before_evals = {e.id: (e.status, e.metrics, e.created_at) for e in test_db.query(Evaluation).all()}
    before_run_evals = {r.id: (r.execution_status, r.decision_signature, r.task_completion) for r in test_db.query(RunEvaluation).all()}

    agg = aggregate_consistency(test_db, eval_ids, persist=True)
    assert agg.id is not None

    after_evals = {e.id: (e.status, e.metrics, e.created_at) for e in test_db.query(Evaluation).all()}
    after_run_evals = {r.id: (r.execution_status, r.decision_signature, r.task_completion) for r in test_db.query(RunEvaluation).all()}

    assert before_evals == after_evals
    assert before_run_evals == after_run_evals

def test_consistency_aggregation_api_endpoints(test_db):
    """Test API endpoints for creating, listing, and retrieving consistency aggregations."""
    eval_ids = []
    for i in range(1, 6):
        eid = f"api_eval_{i}"
        _create_mock_eval_and_runs(test_db, eid, f"api_exp_{i}")
        eval_ids.append(eid)

    from app.database.session import get_db
    app.dependency_overrides[get_db] = lambda: test_db
    client = TestClient(app)

    try:
        # 1. Incompatible / duplicate request returns 400
        res = client.post("/api/evaluations/consistency-aggregations", json={"evaluation_ids": ["api_eval_1", "api_eval_1"]})
        assert res.status_code == 400
        assert res.json()["error"]["code"] == "INVALID_EVALUATION_SET"

        # 2. Valid request creates aggregation (201)
        res = client.post("/api/evaluations/consistency-aggregations", json={"evaluation_ids": eval_ids})
        assert res.status_code == 201
        data = res.json()
        agg_id = data["aggregation_id"]
        assert data["consistent_group_count"] == 6
        assert data["assessable_group_count"] == 6
        assert data["consistency_rate"] == 100.0

        # 3. List aggregations returns created aggregation
        res = client.get("/api/evaluations/consistency-aggregations")
        assert res.status_code == 200
        items = res.json()["items"]
        assert any(x["aggregation_id"] == agg_id for x in items)

        # 4. Get specific aggregation by ID
        res = client.get(f"/api/evaluations/consistency-aggregations/{agg_id}")
        assert res.status_code == 200
        assert res.json()["aggregation_id"] == agg_id
    finally:
        app.dependency_overrides.clear()

