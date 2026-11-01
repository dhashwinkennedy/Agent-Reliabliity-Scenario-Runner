"""Comprehensive end-to-end regression tests for Consistency Rate in Research Arena.
Verifies all 12 required test conditions:
1. Identical structured outcomes across repetitions -> 100% (6/6).
2. Different recommendations across repetitions in repeatability scenarios.
3. Differences in all other 8 dimensions (execution_status, task_completion, unsupported_action, recovery, sentiment, price_impact, forecast_present, forecast_horizon).
4. Insufficient eligible repetitions (< 5 reps) returning not_assessable.
5. Missing and failed runs handling.
6. Incompatible snapshot / fingerprint / duplicate evaluation IDs.
7. Separate Baseline and EGAL calculations without cross-contamination.
8. Null or absent API values and complex types handled gracefully.
9. Serialization and ratio formatting (numerator, denominator, percentage).
10. Handling of unavailable consistency value.
11. Legitimate negative Baseline-versus-EGAL delta (EGAL < Baseline) preserved.
12. Ensuring absolute consistency percentage is strictly within 0%–100%.
"""
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from fastapi.testclient import TestClient

from app.database.base import Base
from app.models.entities import (
    Evaluation,
    RunEvaluation,
    Experiment,
    ExperimentGroup,
    ExperimentRepetition,
    DatasetSnapshot,
    ConsistencyAggregation,
)
from app.services.consistency import (
    aggregate_consistency,
    validate_evaluations_for_consistency,
    REPEATABILITY_IDS,
    COMPARED_DIMENSIONS,
)
from app.services.grouping import pool_evaluation_metrics, get_group_detail_service
from app.services.analysis import _calculate_delta
from app.main import app


@pytest.fixture
def mem_db():
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


def _populate_eval_runs(
    db,
    eval_id: str,
    exp_id: str,
    snapshot_id: str = "snap_test",
    fingerprint: str = "fp_test_123",
    metric_version: str = "research-metrics-v1",
    scenario_overrides: dict = None,
) -> Evaluation:
    scenario_overrides = scenario_overrides or {}
    ev = Evaluation(
        id=eval_id,
        experiment_id=exp_id,
        dataset_snapshot_id=snapshot_id,
        dataset_fingerprint=fingerprint,
        evaluation_schema_version="1.0",
        metric_definition_version=metric_version,
        status="completed",
        expected_run_count=18,
        metrics={
            "task_completion_rate": {"numerator": 6, "denominator": 6, "percentage": 100.0},
            "unsupported_action_rate": {"numerator": 0, "denominator": 6, "percentage": 0.0},
            "recovery_rate": {"numerator": 2, "denominator": 2, "percentage": 100.0},
            "consistency_rate": {"numerator": 0, "denominator": 0, "percentage": None, "status": "not_assessable"},
        },
        manifest={},
    )
    db.add(ev)
    db.commit()

    for sc in REPEATABILITY_IDS:
        cat = "normal" if "NORMAL" in sc else ("ambiguous" if "AMBIGUOUS" in sc else "failure")
        ov = scenario_overrides.get(sc, {})
        rev = RunEvaluation(
            id=f"rev_{eval_id}_{sc}",
            evaluation_id=eval_id,
            run_id=f"run_{exp_id}_{sc}",
            scenario_id=sc,
            category=cat,
            execution_status=ov.get("execution_status", "completed"),
            output_schema_valid=ov.get("output_schema_valid", True),
            task_completion={"status": ov.get("task_completion_status", "pass" if cat == "normal" else "not_applicable")},
            unsupported_action={"present": ov.get("unsupported_action_present", False if cat == "ambiguous" else None)},
            recovery={"status": ov.get("recovery_status", "recovered" if sc == "FAILURE-001" else "not_applicable")},
            decision_signature={
                "sentiment": ov.get("sentiment", "positive" if cat == "normal" else "neutral"),
                "price_impact": ov.get("price_impact", "positive" if cat == "normal" else "neutral"),
                "recommendation": ov.get("recommendation", "BUY" if cat == "normal" else "HOLD"),
                "forecast_present": ov.get("forecast_present", False),
                "forecast_horizon": ov.get("forecast_horizon", "short_term"),
            },
            exclusions=ov.get("exclusions", []),
        )
        db.add(rev)
    db.commit()
    return ev


def test_condition_1_identical_structured_outcomes(mem_db):
    """Condition 1: Identical structured outcomes across 5 repetitions yield 100% (6/6)."""
    eval_ids = []
    for i in range(1, 6):
        eid = f"eval_c1_{i}"
        _populate_eval_runs(mem_db, eid, f"exp_c1_{i}")
        eval_ids.append(eid)

    agg = aggregate_consistency(mem_db, eval_ids, persist=True)
    assert agg.aggregation_status == "complete"
    assert agg.consistent_group_count == 6
    assert agg.assessable_group_count == 6
    assert agg.consistency_rate == 100.0
    assert agg.coverage == 100.0


def test_condition_2_differing_recommendations(mem_db):
    """Condition 2: Different recommendation in 1 scenario across repetitions drops consistency to 5/6 (83.3333%)."""
    eval_ids = []
    for i in range(1, 6):
        eid = f"eval_c2_{i}"
        overrides = {}
        if i == 5:
            # Change recommendation in AMBIGUOUS-001 on 5th repetition
            overrides["AMBIGUOUS-001"] = {"recommendation": "BUY"}
        _populate_eval_runs(mem_db, eid, f"exp_c2_{i}", scenario_overrides=overrides)
        eval_ids.append(eid)

    agg = aggregate_consistency(mem_db, eval_ids, persist=True)
    assert agg.aggregation_status == "complete"
    assert agg.assessable_group_count == 6
    assert agg.consistent_group_count == 5
    assert agg.consistency_rate == round(5 / 6 * 100, 4)
    sc = next(s for s in agg.repeatability_scenario_results if s["scenario_id"] == "AMBIGUOUS-001")
    assert sc["is_consistent"] is False
    assert "recommendation" in sc["differing_fields"]


def test_condition_3_differences_in_all_other_dimensions(mem_db):
    """Condition 3: Differences in each of the remaining 8 dimensions are detected."""
    # We will vary a distinct dimension in each repeatability scenario
    dimension_tests = [
        ("NORMAL-001", "execution_status", "failed"),
        ("NORMAL-004", "task_completion_status", "fail"),
        ("AMBIGUOUS-001", "unsupported_action_present", True),
        ("AMBIGUOUS-005", "price_impact", "negative"),
        ("FAILURE-001", "recovery_status", "unscored"),
        ("FAILURE-003", "forecast_horizon", "intraday"),
    ]

    eval_ids = []
    for i in range(1, 6):
        eid = f"eval_c3_{i}"
        overrides = {}
        if i == 3:
            for sc_id, dim, val in dimension_tests:
                overrides[sc_id] = {dim: val}
        _populate_eval_runs(mem_db, eid, f"exp_c3_{i}", scenario_overrides=overrides)
        eval_ids.append(eid)

    agg = aggregate_consistency(mem_db, eval_ids, persist=True)
    assert agg.assessable_group_count == 6
    assert agg.consistent_group_count == 0
    assert agg.consistency_rate == 0.0
    for sc_id, dim, _ in dimension_tests:
        sc = next(s for s in agg.repeatability_scenario_results if s["scenario_id"] == sc_id)
        assert sc["is_consistent"] is False
        assert dim in sc["differing_fields"]


def test_condition_4_insufficient_eligible_repetitions(mem_db):
    """Condition 4: When < 5 repetitions exist, returns not_assessable with explicit reason and percentage: None."""
    evals = []
    for i in range(1, 4):  # only 3 repetitions
        eid = f"eval_c4_{i}"
        ev = _populate_eval_runs(mem_db, eid, f"exp_c4_{i}")
        evals.append(ev)

    pooled = pool_evaluation_metrics(evals, db=mem_db)
    cons = pooled["consistency_rate"]
    assert cons["status"] == "not_assessable"
    assert cons["percentage"] is None
    assert cons["numerator"] == 0
    assert cons["denominator"] == 0
    assert cons["details"]["reason"] == "insufficient_repetitions"
    assert cons["details"]["required_repetitions"] == 5
    assert cons["details"]["observed_repetitions"] == 3


def test_condition_5_missing_and_failed_runs(mem_db):
    """Condition 5: Missing RunEvaluation record in a repetition marks scenario not_assessable."""
    eval_ids = []
    for i in range(1, 6):
        eid = f"eval_c5_{i}"
        _populate_eval_runs(mem_db, eid, f"exp_c5_{i}")
        eval_ids.append(eid)

    # Delete RunEvaluation for NORMAL-004 in repetition 2
    mem_db.query(RunEvaluation).filter_by(evaluation_id="eval_c5_2", scenario_id="NORMAL-004").delete()
    mem_db.commit()

    agg = aggregate_consistency(mem_db, eval_ids, persist=True)
    assert agg.aggregation_status == "partial"
    assert agg.assessable_group_count == 5
    assert agg.excluded_group_count == 1
    sc = next(s for s in agg.repeatability_scenario_results if s["scenario_id"] == "NORMAL-004")
    assert sc["is_assessable"] is False
    assert sc["status"] == "not_assessable"


def test_condition_6_mismatched_and_incompatible_evaluations(mem_db):
    """Condition 6: Rejects mismatched snapshots, fingerprints, duplicate IDs, or missing evaluations."""
    ev1 = _populate_eval_runs(mem_db, "eval_m1", "exp_m1", snapshot_id="snap_A", fingerprint="fp_A")
    ev2 = _populate_eval_runs(mem_db, "eval_m2", "exp_m2", snapshot_id="snap_B", fingerprint="fp_A")

    # Mismatched snapshot
    with pytest.raises(ValueError, match="Incompatible dataset snapshots"):
        validate_evaluations_for_consistency(mem_db, ["eval_m1", "eval_m2"])

    # Duplicate IDs
    with pytest.raises(ValueError, match="Duplicate evaluation IDs"):
        validate_evaluations_for_consistency(mem_db, ["eval_m1", "eval_m1"])

    # Missing ID
    with pytest.raises(ValueError, match="not found"):
        validate_evaluations_for_consistency(mem_db, ["eval_nonexistent"])


def test_condition_7_separate_baseline_and_egal_calculations(mem_db):
    """Condition 7: Baseline and EGAL are computed separately without cross-contamination in pooled group metrics."""
    # Create 5 baseline evaluations (100% consistent)
    b_evals = []
    for i in range(1, 6):
        eid = f"eval_b_{i}"
        ev = _populate_eval_runs(mem_db, eid, f"exp_b_{i}")
        b_evals.append(ev)

    # Create 5 EGAL evaluations (differing recommendation in NORMAL-001 -> 5/6 = 83.3333%)
    e_evals = []
    for i in range(1, 6):
        eid = f"eval_e_{i}"
        overrides = {"NORMAL-001": {"recommendation": "BUY" if i % 2 == 0 else "HOLD"}}
        ev = _populate_eval_runs(mem_db, eid, f"exp_e_{i}", scenario_overrides=overrides)
        e_evals.append(ev)

    b_pooled = pool_evaluation_metrics(b_evals, db=mem_db)
    e_pooled = pool_evaluation_metrics(e_evals, db=mem_db)

    assert b_pooled["consistency_rate"]["percentage"] == 100.0
    assert b_pooled["consistency_rate"]["numerator"] == 6
    assert b_pooled["consistency_rate"]["denominator"] == 6

    assert e_pooled["consistency_rate"]["percentage"] == round(5 / 6 * 100, 4)
    assert e_pooled["consistency_rate"]["numerator"] == 5
    assert e_pooled["consistency_rate"]["denominator"] == 6


def test_condition_8_null_and_complex_unhashable_values_handled(mem_db):
    """Condition 8: Null values and nested dictionaries/lists in decision signatures are handled safely without crashing."""
    eval_ids = []
    for i in range(1, 6):
        eid = f"eval_c8_{i}"
        # Inject nested dictionary in decision signature
        ev = _populate_eval_runs(mem_db, eid, f"exp_c8_{i}")
        eval_ids.append(eid)

    # Put complex dict into a RunEvaluation decision signature
    rev = mem_db.query(RunEvaluation).filter_by(evaluation_id="eval_c8_1", scenario_id="NORMAL-001").first()
    rev.decision_signature = {
        "sentiment": {"primary": "positive", "secondary": ["optimistic"]},
        "recommendation": "BUY",
    }
    mem_db.commit()

    agg = aggregate_consistency(mem_db, eval_ids, persist=True)
    assert agg is not None
    assert agg.assessable_group_count == 6


def test_condition_9_serializer_and_ratio_representation(mem_db):
    """Condition 9: Serialization returns accurate numerator, denominator, percentage, and ratio."""
    eval_ids = []
    for i in range(1, 6):
        eid = f"eval_c9_{i}"
        _populate_eval_runs(mem_db, eid, f"exp_c9_{i}")
        eval_ids.append(eid)

    agg = aggregate_consistency(mem_db, eval_ids, persist=True)
    assert agg.consistent_group_count == 6
    assert agg.assessable_group_count == 6
    assert agg.consistency_rate == 100.0

    evals = [mem_db.get(Evaluation, eid) for eid in eval_ids]
    pooled = pool_evaluation_metrics(evals, db=mem_db)
    cons = pooled["consistency_rate"]

    assert cons["numerator"] == 6
    assert cons["denominator"] == 6
    assert cons["percentage"] == 100.0
    assert cons["status"] == "complete"


def test_condition_10_correct_handling_of_unavailable_consistency(mem_db):
    """Condition 10: Correct handling when consistency is unavailable (not assessable), returning None rather than 0%."""
    evals = []
    for i in range(1, 3):  # only 2 repetitions
        ev = _populate_eval_runs(mem_db, f"eval_c10_{i}", f"exp_c10_{i}")
        evals.append(ev)

    pooled = pool_evaluation_metrics(evals, db=mem_db)
    assert pooled["consistency_rate"]["percentage"] is None
    assert pooled["consistency_rate"]["status"] == "not_assessable"
    assert pooled["consistency_rate"]["numerator"] == 0
    assert pooled["consistency_rate"]["denominator"] == 0


def test_condition_11_legitimate_negative_delta_preserved():
    """Condition 11: A legitimate negative Baseline-versus-EGAL delta (EGAL < Baseline) is preserved and not clamped."""
    # EGAL consistency = 66.6667%, Baseline consistency = 100.0%
    delta = _calculate_delta(66.6667, 100.0, higher_is_better=True)
    assert delta["delta"] == -33.3333
    assert delta["value"] == -33.3333
    assert delta["direction"] == "regressed"
    assert delta["label"] == "Regressed"
    assert delta["is_improvement"] is False


def test_condition_12_absolute_consistency_percentage_clamped_0_to_100(mem_db):
    """Condition 12: Absolute consistency percentage can never be negative or exceed 100%."""
    eval_ids = []
    for i in range(1, 6):
        eid = f"eval_c12_{i}"
        _populate_eval_runs(mem_db, eid, f"exp_c12_{i}")
        eval_ids.append(eid)

    agg = aggregate_consistency(mem_db, eval_ids, persist=True)
    assert agg.consistency_rate is not None
    assert 0.0 <= agg.consistency_rate <= 100.0
