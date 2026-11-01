"""Cross-experiment consistency aggregation service for Research Arena.
Aggregates saved per-run evaluation records across multiple completed experiments
for the designated repeatability scenarios without calling any agents or providers.
"""
from typing import Any
from sqlalchemy.orm import Session
from app.models.entities import Evaluation, RunEvaluation, ConsistencyAggregation
from app.services.datasets import uid

REPEATABILITY_IDS = [
    "NORMAL-001",
    "NORMAL-004",
    "AMBIGUOUS-001",
    "AMBIGUOUS-005",
    "FAILURE-001",
    "FAILURE-003",
]
PLANNED_REPETITIONS = 5

COMPARED_DIMENSIONS = [
    "execution_status",
    "task_completion_status",
    "unsupported_action_present",
    "recovery_status",
    "sentiment",
    "price_impact",
    "recommendation",
    "forecast_present",
    "forecast_horizon",
]

def validate_evaluations_for_consistency(db: Session, evaluation_ids: list[str]) -> list[Evaluation]:
    """Validates that evaluation IDs exist, are completed, distinct, and share compatible snapshots,
    fingerprints, and metric definition versions."""
    if not evaluation_ids:
        raise ValueError("At least one evaluation ID must be provided for consistency aggregation")
    
    if len(evaluation_ids) != len(set(evaluation_ids)):
        raise ValueError("Duplicate evaluation IDs provided in request")
    
    evals: list[Evaluation] = []
    for eid in evaluation_ids:
        ev = db.get(Evaluation, eid)
        if not ev:
            raise ValueError(f"Evaluation '{eid}' not found or inaccessible")
        if ev.status != "completed":
            raise ValueError(f"Evaluation '{eid}' has incomplete status: '{ev.status}'")
        evals.append(ev)
    
    snapshots = {ev.dataset_snapshot_id for ev in evals}
    if len(snapshots) > 1:
        raise ValueError(f"Incompatible dataset snapshots across evaluations: {sorted(list(snapshots))}")
    
    fingerprints = {ev.dataset_fingerprint for ev in evals}
    if len(fingerprints) > 1:
        raise ValueError(f"Incompatible dataset fingerprints across evaluations: {sorted(list(fingerprints))}")
    
    versions = {ev.metric_definition_version for ev in evals}
    if len(versions) > 1:
        raise ValueError(f"Incompatible metric definition versions across evaluations: {sorted(list(versions))}")
    
    return evals

def aggregate_consistency(
    db: Session,
    evaluation_ids: list[str],
    persist: bool = True,
) -> ConsistencyAggregation:
    """Aggregates consistency across repetitions using saved RunEvaluation records."""
    evals = validate_evaluations_for_consistency(db, evaluation_ids)
    snapshot_id = evals[0].dataset_snapshot_id
    fingerprint = evals[0].dataset_fingerprint
    metric_version = evals[0].metric_definition_version
    
    scenario_results: list[dict[str, Any]] = []
    
    for scenario_id in REPEATABILITY_IDS:
        cat = "normal" if "NORMAL" in scenario_id else ("ambiguous" if "AMBIGUOUS" in scenario_id else "failure")
        repetitions: list[dict[str, Any]] = []
        is_missing_any = False
        
        for ev in evals:
            rev = db.query(RunEvaluation).filter_by(evaluation_id=ev.id, scenario_id=scenario_id).first()
            if not rev:
                is_missing_any = True
                repetitions.append({
                    "evaluation_id": ev.id,
                    "experiment_id": ev.experiment_id,
                    "run_id": None,
                    "execution_status": "missing",
                    "output_schema_valid": False,
                    "task_completion_status": None,
                    "unsupported_action_present": None,
                    "recovery_status": None,
                    "sentiment": None,
                    "price_impact": None,
                    "recommendation": None,
                    "forecast_present": None,
                    "forecast_horizon": None,
                    "exclusions": ["RUN_RECORD_MISSING"],
                })
            else:
                sig = rev.decision_signature or {}
                t_stat = (rev.task_completion or {}).get("status")
                ua_pres = (rev.unsupported_action or {}).get("present")
                rec_stat = (rev.recovery or {}).get("status")
                repetitions.append({
                    "evaluation_id": ev.id,
                    "experiment_id": ev.experiment_id,
                    "run_id": rev.run_id,
                    "execution_status": rev.execution_status,
                    "output_schema_valid": rev.output_schema_valid,
                    "task_completion_status": t_stat,
                    "unsupported_action_present": ua_pres,
                    "recovery_status": rec_stat,
                    "sentiment": sig.get("sentiment"),
                    "price_impact": sig.get("price_impact"),
                    "recommendation": sig.get("recommendation"),
                    "forecast_present": sig.get("forecast_present"),
                    "forecast_horizon": sig.get("forecast_horizon"),
                    "exclusions": rev.exclusions or [],
                })
        
        # Check differences across defined dimensions
        differing_fields: dict[str, list[Any]] = {}
        for dim in COMPARED_DIMENSIONS:
            vals = [r[dim] for r in repetitions]
            # Convert dicts/lists if any to hashable structures
            def _to_hashable(v: Any) -> Any:
                if isinstance(v, dict):
                    return tuple(sorted((k, _to_hashable(val)) for k, val in v.items()))
                if isinstance(v, list):
                    return tuple(_to_hashable(val) for val in v)
                return v

            distinct_vals = {_to_hashable(v) for v in vals}
            if len(distinct_vals) > 1:
                differing_fields[dim] = vals
        
        if is_missing_any or len(evals) < PLANNED_REPETITIONS:
            status = "not_assessable"
            is_assessable = False
            is_consistent = False
        else:
            is_assessable = True
            if len(differing_fields) == 0:
                status = "consistent"
                is_consistent = True
            else:
                status = "inconsistent"
                is_consistent = False
        
        scenario_results.append({
            "scenario_id": scenario_id,
            "category": cat,
            "status": status,
            "is_consistent": is_consistent,
            "is_assessable": is_assessable,
            "repetition_count": len(repetitions),
            "expected_repetitions": PLANNED_REPETITIONS,
            "differing_fields": differing_fields,
            "repetitions": repetitions,
        })
    
    consistent_group_count = sum(1 for s in scenario_results if s["is_consistent"])
    assessable_group_count = sum(1 for s in scenario_results if s["is_assessable"])
    excluded_group_count = len(scenario_results) - assessable_group_count
    coverage = round(assessable_group_count / len(scenario_results) * 100, 4) if scenario_results else 0.0
    consistency_rate = round(consistent_group_count / assessable_group_count * 100, 4) if assessable_group_count > 0 else None
    if consistency_rate is not None:
        consistency_rate = max(0.0, min(100.0, consistency_rate))
    
    if assessable_group_count == len(scenario_results):
        aggregation_status = "complete"
    elif assessable_group_count > 0:
        aggregation_status = "partial"
    else:
        aggregation_status = "not_assessable"
    
    if persist:
        # Check if identical aggregation already exists to prevent duplicate rows
        existing = (
            db.query(ConsistencyAggregation)
            .filter_by(
                dataset_snapshot_id=snapshot_id,
                metric_definition_version=metric_version,
            )
            .all()
        )
        for ex in existing:
            if sorted(ex.selected_evaluation_ids or []) == sorted(evaluation_ids):
                ex.aggregation_status = aggregation_status
                ex.repeatability_scenario_results = scenario_results
                ex.consistent_group_count = consistent_group_count
                ex.assessable_group_count = assessable_group_count
                ex.excluded_group_count = excluded_group_count
                ex.coverage = coverage
                ex.consistency_rate = consistency_rate
                db.commit()
                db.refresh(ex)
                return ex

    agg = ConsistencyAggregation(
        id=uid("agg_"),
        selected_evaluation_ids=evaluation_ids,
        dataset_snapshot_id=snapshot_id,
        dataset_fingerprint=fingerprint,
        metric_definition_version=metric_version,
        aggregation_status=aggregation_status,
        repeatability_scenario_results=scenario_results,
        consistent_group_count=consistent_group_count,
        assessable_group_count=assessable_group_count,
        excluded_group_count=excluded_group_count,
        coverage=coverage,
        consistency_rate=consistency_rate,
    )
    
    if persist:
        db.add(agg)
        db.commit()
        db.refresh(agg)
    
    return agg

def consistency_aggregation_out(agg: ConsistencyAggregation) -> dict[str, Any]:
    """Formats ConsistencyAggregation record for API responses."""
    return {
        "aggregation_id": agg.id,
        "selected_evaluation_ids": agg.selected_evaluation_ids,
        "dataset_snapshot_id": agg.dataset_snapshot_id,
        "dataset_fingerprint": agg.dataset_fingerprint,
        "metric_definition_version": agg.metric_definition_version,
        "aggregation_status": agg.aggregation_status,
        "consistent_group_count": agg.consistent_group_count,
        "assessable_group_count": agg.assessable_group_count,
        "excluded_group_count": agg.excluded_group_count,
        "coverage": agg.coverage,
        "consistency_rate": agg.consistency_rate,
        "repeatability_scenario_results": agg.repeatability_scenario_results,
        "created_at": agg.created_at.isoformat() if agg.created_at else None,
    }
