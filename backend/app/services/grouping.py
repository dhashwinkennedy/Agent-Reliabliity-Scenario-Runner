"""Experiment grouping and Baseline-versus-EGAL comparison service for Research Arena.
Preserves separate execution histories, repetitions, and evaluations.
Groups compatible experiments using the same dataset snapshot, provider, and model conditions.
Never merges runs destructively and never alters agent behavior.
"""
import io
import csv
import json
import uuid
from datetime import datetime
from typing import Any
from sqlalchemy.orm import Session
from fastapi import HTTPException

from app.models.entities import (
    Experiment,
    ExperimentGroup,
    ExperimentRepetition,
    Run,
    Evaluation,
    DatasetSnapshot,
    Dataset,
)
from app.services.datasets import uid
from app.services.experiments import create_runs, start, to_json_safe
from app.services.evaluation import evaluation_out, METRIC_DEFINITION_VERSION
from app.services.analysis import _resolve_model, _determine_condition, _calculate_delta
from app.integrations.registry import resolve_agent, providers
from app.schemas.api import ExperimentGroupCreate, ExperimentGroupLink


def repetition_summary(rep: ExperimentRepetition, db: Session | None = None) -> dict[str, Any]:
    eval_data = None
    if rep.evaluation_id and db:
        ev = db.get(Evaluation, rep.evaluation_id)
        if ev:
            eval_data = {
                "id": ev.id,
                "status": ev.status,
                "metrics": ev.metrics,
                "manifest": ev.manifest,
            }
    return {
        "id": rep.id,
        "repetition_id": rep.id,
        "experiment_id": rep.experiment_id,
        "repetition_index": rep.repetition_index,
        "status": rep.status,
        "run_count": rep.run_count,
        "completed_run_count": rep.completed_run_count,
        "failed_run_count": rep.failed_run_count,
        "evaluation_id": rep.evaluation_id,
        "evaluation": eval_data,
        "idempotency_key": rep.idempotency_key,
        "created_at": rep.created_at.isoformat() if rep.created_at else None,
        "started_at": rep.started_at.isoformat() if rep.started_at else None,
        "completed_at": rep.completed_at.isoformat() if rep.completed_at else None,
    }


def get_experiment_repetitions(db: Session, experiment_id: str) -> list[dict[str, Any]]:
    reps = (
        db.query(ExperimentRepetition)
        .filter_by(experiment_id=experiment_id)
        .order_by(ExperimentRepetition.repetition_index.asc())
        .all()
    )
    if reps:
        return [repetition_summary(r, db) for r in reps]

    # Legacy or direct run fallback: synthesize Repetition 1
    runs = db.query(Run).filter_by(experiment_id=experiment_id).all()
    if not runs:
        return []

    exp = db.get(Experiment, experiment_id)
    comp = sum(1 for r in runs if r.status == "completed")
    fail = sum(1 for r in runs if r.status == "failed")
    latest_eval = (
        db.query(Evaluation)
        .filter_by(experiment_id=experiment_id, status="completed")
        .order_by(Evaluation.created_at.desc())
        .first()
    )
    first_started = min((r.started_at for r in runs if r.started_at), default=None)
    last_completed = max((r.completed_at for r in runs if r.completed_at), default=None)
    status = exp.status if exp else ("completed" if comp == len(runs) else "running")

    return [{
        "id": f"rep_{experiment_id}_1",
        "repetition_id": f"rep_{experiment_id}_1",
        "experiment_id": experiment_id,
        "repetition_index": 1,
        "status": status,
        "run_count": len(runs),
        "completed_run_count": comp,
        "failed_run_count": fail,
        "evaluation_id": latest_eval.id if latest_eval else None,
        "evaluation": {
            "id": latest_eval.id,
            "status": latest_eval.status,
            "metrics": latest_eval.metrics,
            "manifest": latest_eval.manifest,
        } if latest_eval else None,
        "idempotency_key": None,
        "created_at": exp.created_at.isoformat() if exp and exp.created_at else None,
        "started_at": first_started.isoformat() if first_started else None,
        "completed_at": last_completed.isoformat() if last_completed else None,
    }]


def validate_group_compatibility(db: Session, experiments: list[Experiment]) -> tuple[str, str, str]:
    """Ensures experiments share identical immutable dataset snapshot, provider, and model conditions.
    Rejects incompatible experiments and prevents grouping unrelated experiments solely by name.
    """
    if len(experiments) < 2:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INCOMPATIBLE_EXPERIMENT_GROUP",
                "message": "At least two experiments are required to form a comparison group.",
            },
        )

    snapshots = {e.dataset_snapshot_id for e in experiments}
    if len(snapshots) > 1:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INCOMPATIBLE_EXPERIMENT_GROUP",
                "message": f"Cannot group experiments across different dataset snapshots: {sorted(list(snapshots))}",
            },
        )
    snapshot_id = list(snapshots)[0]

    providers_set = {e.provider_id for e in experiments}
    if len(providers_set) > 1:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INCOMPATIBLE_EXPERIMENT_GROUP",
                "message": f"Cannot group experiments across different providers: {sorted(list(providers_set))}",
            },
        )
    provider_id = list(providers_set)[0]

    models_set = {_resolve_model(e, db) for e in experiments}
    if len(models_set) > 1:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INCOMPATIBLE_EXPERIMENT_GROUP",
                "message": f"Cannot group experiments with different models: {sorted(list(models_set))}",
            },
        )
    model = list(models_set)[0]

    conditions = {_determine_condition(e.agent_id) for e in experiments}
    if "baseline" not in conditions or "egal" not in conditions:
        raise HTTPException(
            status_code=422,
            detail={
                "code": "INCOMPATIBLE_EXPERIMENT_GROUP",
                "message": (
                    f"A comparison group must contain both a Baseline condition ('financial_news_analysis') "
                    f"and an EGAL condition ('financial_news_analysis_egal'). Found conditions: {sorted(list(conditions))}"
                ),
            },
        )

    return snapshot_id, provider_id, model


def create_experiment_group_service(
    db: Session,
    body: ExperimentGroupCreate,
    db_factory = None,
) -> dict[str, Any]:
    """Creates a new ExperimentGroup and automatically provisions paired Baseline and EGAL experiments."""
    snapshot = db.get(DatasetSnapshot, body.dataset_snapshot_id)
    if not snapshot:
        raise HTTPException(404, detail={"code": "SNAPSHOT_NOT_FOUND", "message": f"Dataset snapshot '{body.dataset_snapshot_id}' not found"})

    baseline_agent = resolve_agent(db, "financial_news_analysis")
    egal_agent = resolve_agent(db, "financial_news_analysis_egal")
    if not baseline_agent or not baseline_agent.metadata().get("ready"):
        raise HTTPException(422, detail={"code": "AGENT_UNAVAILABLE", "message": "Baseline agent 'financial_news_analysis' is unavailable"})
    if not egal_agent or not egal_agent.metadata().get("ready"):
        raise HTTPException(422, detail={"code": "AGENT_UNAVAILABLE", "message": "EGAL agent 'financial_news_analysis_egal' is unavailable"})

    # Resolve provider snapshot
    provider_snapshot = None
    if body.provider_id in providers:
        provider_snapshot = providers[body.provider_id].metadata()
    else:
        from app.services import providers as provider_service
        try:
            prov = provider_service.get_provider(db, body.provider_id)
            provider_snapshot = provider_service.metadata(prov)
        except Exception as exc:
            raise HTTPException(422, detail={"code": "PROVIDER_ERROR", "message": str(exc)})

    chosen_model = body.model or (
        provider_snapshot.get("default_model") or provider_snapshot.get("model")
        if isinstance(provider_snapshot, dict) else None
    )
    if not chosen_model and body.provider_id in providers:
        prov_models = providers[body.provider_id].metadata().get("models", [])
        if prov_models:
            chosen_model = prov_models[0]

    safe_provider = to_json_safe(provider_snapshot)
    if safe_provider and isinstance(safe_provider, dict) and chosen_model:
        safe_provider["model"] = chosen_model

    group_id = body.group_id or uid("grp")
    existing_grp = db.get(ExperimentGroup, group_id)
    if existing_grp:
        raise HTTPException(409, detail={"code": "GROUP_ID_CONFLICT", "message": f"Experiment group '{group_id}' already exists"})

    group = ExperimentGroup(
        id=group_id,
        name=body.name,
        dataset_snapshot_id=body.dataset_snapshot_id,
        provider_id=body.provider_id,
        model=chosen_model,
        created_at=datetime.utcnow(),
    )
    db.add(group)

    # Baseline Experiment
    exp_base = Experiment(
        id=uid("exp"),
        name=f"{body.name} (Baseline)",
        group_id=group_id,
        group_name=body.name,
        dataset_snapshot_id=body.dataset_snapshot_id,
        agent_id="financial_news_analysis",
        agent_version=baseline_agent.metadata().get("version", "unknown"),
        agent_configuration_snapshot=to_json_safe(body.baseline_configuration),
        provider_id=body.provider_id,
        provider_metadata_snapshot=safe_provider,
        model=chosen_model,
        input_mapping=body.input_mapping,
        status="draft",
        created_at=datetime.utcnow(),
    )
    db.add(exp_base)

    # EGAL Experiment
    exp_egal = Experiment(
        id=uid("exp"),
        name=f"{body.name} (EGAL)",
        group_id=group_id,
        group_name=body.name,
        dataset_snapshot_id=body.dataset_snapshot_id,
        agent_id="financial_news_analysis_egal",
        agent_version=egal_agent.metadata().get("version", "unknown"),
        agent_configuration_snapshot=to_json_safe(body.egal_configuration),
        provider_id=body.provider_id,
        provider_metadata_snapshot=safe_provider,
        model=chosen_model,
        input_mapping=body.input_mapping,
        status="draft",
        created_at=datetime.utcnow(),
    )
    db.add(exp_egal)
    db.commit()

    if body.auto_start and db_factory:
        # Create repetition 1 and start each
        for exp in (exp_base, exp_egal):
            rep = ExperimentRepetition(
                id=uid("rep"),
                experiment_id=exp.id,
                repetition_index=1,
                status="starting",
                created_at=datetime.utcnow(),
                started_at=datetime.utcnow(),
            )
            db.add(rep)
            db.flush()
            runs = create_runs(db, exp, repetition_id=rep.id, repetition_index=1)
            rep.run_count = len(runs)
            exp.status = "starting"
            db.commit()
            start(db_factory, exp.id, repetition_id=rep.id)

    return get_group_detail_service(db, group_id)


def link_experiments_to_group_service(
    db: Session,
    body: ExperimentGroupLink,
) -> dict[str, Any]:
    """Links existing compatible experiments into a comparison group."""
    exps = [db.get(Experiment, eid) for eid in body.experiment_ids]
    for idx, eid in enumerate(body.experiment_ids):
        if not exps[idx]:
            raise HTTPException(404, detail={"code": "EXPERIMENT_NOT_FOUND", "message": f"Experiment '{eid}' not found"})

    snapshot_id, provider_id, model = validate_group_compatibility(db, exps)
    existing_group_ids = {e.group_id for e in exps if e.group_id}
    if not body.group_id and len(existing_group_ids) == 1 and list(existing_group_ids)[0]:
        group_id = list(existing_group_ids)[0]
    else:
        group_id = body.group_id or uid("grp")

    group = db.get(ExperimentGroup, group_id)
    if not group:
        group = ExperimentGroup(
            id=group_id,
            name=body.group_name,
            dataset_snapshot_id=snapshot_id,
            provider_id=provider_id,
            model=model,
            created_at=datetime.utcnow(),
        )
        db.add(group)
    else:
        group.name = body.group_name
        group.dataset_snapshot_id = snapshot_id
        group.provider_id = provider_id
        group.model = model

    for exp in exps:
        exp.group_id = group_id
        exp.group_name = body.group_name

    db.commit()
    return get_group_detail_service(db, group_id)


def pool_evaluation_metrics(
    evaluations: list[Evaluation],
    db: Session | None = None,
) -> dict[str, Any]:
    """Pools multiple repetition evaluation metrics into authoritative aggregated metrics.
    Sums numerators and denominators to prevent ratio distortion across differing exclusions.
    Calculates cross-repetition Consistency Rate across the 6 repeatability scenarios when >= 5 repetitions.
    """
    if not evaluations:
        return {}

    eval_metrics_list = []
    for ev in evaluations:
        if ev and ev.metrics:
            m = ev.metrics
            if isinstance(m, str):
                try:
                    m = json.loads(m)
                except Exception:
                    m = {}
            if isinstance(m, dict):
                eval_metrics_list.append(m)

    if not eval_metrics_list:
        return {}

    def _pool(metric_key: str, notes_default: list[str]) -> dict[str, Any]:
        num = sum(m.get(metric_key, {}).get("numerator", 0) for m in eval_metrics_list)
        den = sum(m.get(metric_key, {}).get("denominator", 0) for m in eval_metrics_list)
        pct = round((num / den) * 100.0, 4) if den > 0 else None
        excluded = sum(m.get(metric_key, {}).get("excluded_runs", 0) for m in eval_metrics_list)
        missing = sum(m.get(metric_key, {}).get("missing_runs", 0) for m in eval_metrics_list)
        review = sum(m.get(metric_key, {}).get("requires_review", 0) for m in eval_metrics_list)
        status = "complete" if (den > 0 and review == 0) else ("partial" if review > 0 else "not_assessable")
        tot = den + review + missing + excluded
        coverage = round((den / tot) * 100.0, 2) if tot > 0 else 100.0
        return {
            "metric_name": metric_key,
            "metric_version": METRIC_DEFINITION_VERSION,
            "numerator": num,
            "denominator": den,
            "percentage": pct,
            "excluded_runs": excluded,
            "missing_runs": missing,
            "requires_review": review,
            "assessment_coverage": coverage,
            "status": status,
            "notes": notes_default,
            "details": {
                "contributing_evaluations": len(eval_metrics_list),
            },
        }

    pooled = {
        "task_completion_rate": _pool(
            "task_completion_rate",
            ["Pooled across completed repetitions. Evaluates deterministically assessed normal scenarios meeting all ground truth requirements."],
        ),
        "unsupported_action_rate": _pool(
            "unsupported_action_rate",
            ["Pooled across completed repetitions. Evaluates whether the agent took unsupported directional actions (BUY/SELL) in ambiguous scenarios."],
        ),
        "recovery_rate": _pool(
            "recovery_rate",
            ["Pooled across completed repetitions. Scored on recoverable failure scenarios (FAILURE-001, FAILURE-002). Persistent failures are excluded."],
        ),
        "false_success_rate": _pool(
            "false_success_rate",
            ["Pooled across completed repetitions. Supporting check: identifies scenarios claiming execution success despite ungrounded or persistent failure outputs."],
        ),
    }

    rep_count = len(eval_metrics_list)
    if rep_count < 5:
        pooled["consistency_rate"] = {
            "metric_name": "consistency_rate",
            "metric_version": METRIC_DEFINITION_VERSION,
            "numerator": 0,
            "denominator": 0,
            "percentage": None,
            "status": "not_assessable",
            "notes": [f"Not assessable: requires 5 completed repetitions according to research-metrics-v1 protocol ({rep_count} of 5 completed)."],
            "details": {
                "reason": "insufficient_repetitions",
                "required_repetitions": 5,
                "observed_repetitions": rep_count,
            },
        }
    else:
        # 5 or more completed repetitions: compute cross-repetition consistency
        session = db
        if not session and evaluations:
            try:
                from sqlalchemy.orm import object_session
                session = object_session(evaluations[0])
            except Exception:
                session = None

        if session:
            try:
                from app.services.consistency import aggregate_consistency
                eval_ids = [ev.id for ev in evaluations[:5]]
                agg = aggregate_consistency(session, eval_ids, persist=True)

                pooled["consistency_rate"] = {
                    "metric_name": "consistency_rate",
                    "metric_version": agg.metric_definition_version or METRIC_DEFINITION_VERSION,
                    "numerator": agg.consistent_group_count,
                    "denominator": agg.assessable_group_count,
                    "percentage": agg.consistency_rate,
                    "excluded_runs": agg.excluded_group_count,
                    "missing_runs": 0,
                    "requires_review": 0,
                    "assessment_coverage": agg.coverage,
                    "status": agg.aggregation_status,
                    "notes": ["Evaluates decision stability across the 6 designated repeatability scenarios."],
                    "details": {
                        "contributing_evaluations": len(eval_ids),
                        "required_repetitions": 5,
                        "observed_repetitions": rep_count,
                        "aggregation_id": agg.id,
                        "repeatability_scenarios": [s["scenario_id"] for s in (agg.repeatability_scenario_results or [])],
                        "scenario_results": agg.repeatability_scenario_results,
                    },
                }
            except Exception as exc:
                pooled["consistency_rate"] = {
                    "metric_name": "consistency_rate",
                    "metric_version": METRIC_DEFINITION_VERSION,
                    "numerator": 0,
                    "denominator": 0,
                    "percentage": None,
                    "status": "not_assessable",
                    "notes": [f"Consistency aggregation error: {str(exc)}"],
                    "details": {
                        "reason": "aggregation_failed",
                        "error": str(exc),
                        "contributing_evaluations": rep_count,
                    },
                }
        else:
            pooled["consistency_rate"] = {
                "metric_name": "consistency_rate",
                "metric_version": METRIC_DEFINITION_VERSION,
                "numerator": 0,
                "denominator": 0,
                "percentage": None,
                "status": "not_assessable",
                "notes": ["Not assessable: database session required to aggregate RunEvaluation records across repetitions."],
                "details": {
                    "reason": "no_database_session",
                    "required_repetitions": 5,
                    "observed_repetitions": rep_count,
                },
            }

    return pooled


def calculate_baseline_egal_comparison(
    baseline_eval: Evaluation | None,
    egal_eval: Evaluation | None,
    model: str = "unknown",
    provider: str = "unknown",
) -> dict[str, Any]:
    """Computes directional deltas between Baseline and EGAL evaluations."""
    has_b = bool(baseline_eval and baseline_eval.metrics)
    has_e = bool(egal_eval and egal_eval.metrics)

    b_metrics = baseline_eval.metrics if has_b else {}
    if isinstance(b_metrics, str):
        try:
            b_metrics = json.loads(b_metrics)
        except Exception:
            b_metrics = {}

    e_metrics = egal_eval.metrics if has_e else {}
    if isinstance(e_metrics, str):
        try:
            e_metrics = json.loads(e_metrics)
        except Exception:
            e_metrics = {}

    b_tc = b_metrics.get("task_completion_rate", {}).get("percentage")
    e_tc = e_metrics.get("task_completion_rate", {}).get("percentage")

    b_ua = b_metrics.get("unsupported_action_rate", {}).get("percentage")
    e_ua = e_metrics.get("unsupported_action_rate", {}).get("percentage")

    b_rec = b_metrics.get("recovery_rate", {}).get("percentage")
    e_rec = e_metrics.get("recovery_rate", {}).get("percentage")

    b_cons = b_metrics.get("consistency_rate", {}).get("percentage")
    e_cons = e_metrics.get("consistency_rate", {}).get("percentage")

    b_fs_cnt = b_metrics.get("false_success_rate", {}).get("numerator", 0)
    e_fs_cnt = e_metrics.get("false_success_rate", {}).get("numerator", 0)

    b_fs_rate = b_metrics.get("false_success_rate", {}).get("percentage")
    e_fs_rate = e_metrics.get("false_success_rate", {}).get("percentage")

    deltas = {
        "task_completion_rate": _calculate_delta(e_tc, b_tc, higher_is_better=True),
        "unsupported_action_rate": _calculate_delta(e_ua, b_ua, higher_is_better=False),
        "recovery_rate": _calculate_delta(e_rec, b_rec, higher_is_better=True),
        "consistency_rate": _calculate_delta(e_cons, b_cons, higher_is_better=True),
        "false_success_count": _calculate_delta(e_fs_cnt, b_fs_cnt, higher_is_better=False),
        "false_success_rate": _calculate_delta(e_fs_rate, b_fs_rate, higher_is_better=False),
    }

    return {
        "available": has_b and has_e,
        "model": model,
        "provider": provider,
        "baseline_has_evaluation": has_b,
        "egal_has_evaluation": has_e,
        "baseline_metrics": b_metrics,
        "egal_metrics": e_metrics,
        "delta": deltas,
        "deltas": deltas,
    }


def get_group_detail_service(db: Session, group_id: str) -> dict[str, Any]:
    """Returns complete group details, separated baseline/egal execution histories, and comparison."""
    group = db.get(ExperimentGroup, group_id)
    experiments = db.query(Experiment).filter_by(group_id=group_id).order_by(Experiment.created_at.asc()).all()

    if not group and not experiments:
        raise HTTPException(404, detail={"code": "GROUP_NOT_FOUND", "message": f"Experiment group '{group_id}' not found"})

    group_name = group.name if group else (experiments[0].group_name or group_id)
    snapshot_id = group.dataset_snapshot_id if group else experiments[0].dataset_snapshot_id
    provider_id = group.provider_id if group else experiments[0].provider_id
    model = group.model if group else _resolve_model(experiments[0], db)

    baseline_exps = [e for e in experiments if _determine_condition(e.agent_id) == "baseline"]
    egal_exps = [e for e in experiments if _determine_condition(e.agent_id) == "egal"]

    baseline_exp = baseline_exps[0] if baseline_exps else None
    egal_exp = egal_exps[0] if egal_exps else None

    baseline_repetitions = get_experiment_repetitions(db, baseline_exp.id) if baseline_exp else []
    egal_repetitions = get_experiment_repetitions(db, egal_exp.id) if egal_exp else []

    # Collect completed evaluations across repetitions
    b_eval_ids = [r["evaluation_id"] for r in baseline_repetitions if r.get("evaluation_id")]
    e_eval_ids = [r["evaluation_id"] for r in egal_repetitions if r.get("evaluation_id")]
    b_completed_evals = [ev for eid in b_eval_ids if (ev := db.get(Evaluation, eid)) and ev.status == "completed"]
    e_completed_evals = [ev for eid in e_eval_ids if (ev := db.get(Evaluation, eid)) and ev.status == "completed"]

    # Calculate pooled across-repetition metrics
    pooled_b_metrics = pool_evaluation_metrics(b_completed_evals, db=db)
    pooled_e_metrics = pool_evaluation_metrics(e_completed_evals, db=db)

    # Compute pooled deltas
    pooled_b_tc = pooled_b_metrics.get("task_completion_rate", {}).get("percentage")
    pooled_e_tc = pooled_e_metrics.get("task_completion_rate", {}).get("percentage")

    pooled_b_ua = pooled_b_metrics.get("unsupported_action_rate", {}).get("percentage")
    pooled_e_ua = pooled_e_metrics.get("unsupported_action_rate", {}).get("percentage")

    pooled_b_rec = pooled_b_metrics.get("recovery_rate", {}).get("percentage")
    pooled_e_rec = pooled_e_metrics.get("recovery_rate", {}).get("percentage")

    pooled_b_cons = pooled_b_metrics.get("consistency_rate", {}).get("percentage")
    pooled_e_cons = pooled_e_metrics.get("consistency_rate", {}).get("percentage")

    pooled_b_fs_cnt = pooled_b_metrics.get("false_success_rate", {}).get("numerator", 0)
    pooled_e_fs_cnt = pooled_e_metrics.get("false_success_rate", {}).get("numerator", 0)

    pooled_b_fs_rate = pooled_b_metrics.get("false_success_rate", {}).get("percentage")
    pooled_e_fs_rate = pooled_e_metrics.get("false_success_rate", {}).get("percentage")

    pooled_deltas = {
        "task_completion_rate": _calculate_delta(pooled_e_tc, pooled_b_tc, higher_is_better=True),
        "unsupported_action_rate": _calculate_delta(pooled_e_ua, pooled_b_ua, higher_is_better=False),
        "recovery_rate": _calculate_delta(pooled_e_rec, pooled_b_rec, higher_is_better=True),
        "consistency_rate": _calculate_delta(pooled_e_cons, pooled_b_cons, higher_is_better=True),
        "false_success_count": _calculate_delta(pooled_e_fs_cnt, pooled_b_fs_cnt, higher_is_better=False),
        "false_success_rate": _calculate_delta(pooled_e_fs_rate, pooled_b_fs_rate, higher_is_better=False),
    }

    across_summary = {
        "available": bool(pooled_b_metrics and pooled_e_metrics),
        "is_pooled": True,
        "model": model,
        "provider": provider_id,
        "repetition_count": min(len(b_completed_evals), len(e_completed_evals)),
        "baseline_repetition_count": len(b_completed_evals),
        "egal_repetition_count": len(e_completed_evals),
        "baseline_metrics": pooled_b_metrics,
        "egal_metrics": pooled_e_metrics,
        "delta": pooled_deltas,
        "deltas": pooled_deltas,
    }

    comparison = across_summary

    latest_b_eval = b_completed_evals[-1] if b_completed_evals else None
    latest_e_eval = e_completed_evals[-1] if e_completed_evals else None

    # Paired repetition comparisons (pairing repetition 1 with repetition 1, etc.)
    paired_reps = []
    max_idx = max(
        max((r["repetition_index"] for r in baseline_repetitions), default=0),
        max((r["repetition_index"] for r in egal_repetitions), default=0),
    )
    for idx in range(1, max_idx + 1):
        b_rep = next((r for r in baseline_repetitions if r["repetition_index"] == idx), None)
        e_rep = next((r for r in egal_repetitions if r["repetition_index"] == idx), None)
        ev_b = db.get(Evaluation, b_rep["evaluation_id"]) if (b_rep and b_rep.get("evaluation_id")) else None
        ev_e = db.get(Evaluation, e_rep["evaluation_id"]) if (e_rep and e_rep.get("evaluation_id")) else None
        rep_comp = calculate_baseline_egal_comparison(ev_b, ev_e, model=model, provider=provider_id)
        paired_reps.append({
            "repetition_index": idx,
            "baseline_repetition": b_rep,
            "egal_repetition": e_rep,
            "baseline_metrics": rep_comp.get("baseline_metrics", {}),
            "egal_metrics": rep_comp.get("egal_metrics", {}),
            "deltas": rep_comp.get("deltas", {}),
            "comparison": rep_comp,
        })

    from app.api.v1.routes import exp_out
    return {
        "id": group_id,
        "group_id": group_id,
        "name": group_name,
        "group_name": group_name,
        "dataset_snapshot_id": snapshot_id,
        "provider_id": provider_id,
        "model": model,
        "created_at": group.created_at.isoformat() if group and group.created_at else (experiments[0].created_at.isoformat() if experiments else None),
        "baseline": {
            "experiment": exp_out(baseline_exp) if baseline_exp else None,
            "condition": "baseline",
            "repetitions": baseline_repetitions,
            "repetition_count": len(baseline_repetitions),
            "latest_evaluation": evaluation_out(latest_b_eval) if latest_b_eval else None,
            "pooled_metrics": pooled_b_metrics,
        },
        "egal": {
            "experiment": exp_out(egal_exp) if egal_exp else None,
            "condition": "egal",
            "repetitions": egal_repetitions,
            "repetition_count": len(egal_repetitions),
            "latest_evaluation": evaluation_out(latest_e_eval) if latest_e_eval else None,
            "pooled_metrics": pooled_e_metrics,
        },
        "comparison": comparison,
        "across_repetition_summary": across_summary,
        "repetition_comparisons": paired_reps,
    }


def list_groups_service(db: Session) -> list[dict[str, Any]]:
    """Lists all experiment groups with summary metrics."""
    groups = db.query(ExperimentGroup).order_by(ExperimentGroup.created_at.desc()).all()
    grouped_ids = {g.id for g in groups}

    # Also discover any distinct group_ids on experiments that don't have an ExperimentGroup record
    extra_exps = db.query(Experiment).filter(Experiment.group_id.isnot(None)).all()
    for e in extra_exps:
        if e.group_id and e.group_id not in grouped_ids:
            grouped_ids.add(e.group_id)

    results = []
    for gid in sorted(list(grouped_ids)):
        try:
            detail = get_group_detail_service(db, gid)
            results.append(detail)
        except Exception:
            pass
    return results


def export_group_service(db: Session, group_id: str, format: str) -> tuple[str, str, str]:
    """Exports grouped comparison data and run results in CSV or JSONL."""
    if format not in {"jsonl", "csv"}:
        raise HTTPException(415, detail={"code": "UNSUPPORTED_EXPORT_FORMAT", "message": "Supported formats: jsonl, csv"})

    detail = get_group_detail_service(db, group_id)
    b_exp_id = (detail.get("baseline") or {}).get("experiment", {}).get("id")
    e_exp_id = (detail.get("egal") or {}).get("experiment", {}).get("id")

    b_runs = db.query(Run).filter_by(experiment_id=b_exp_id).order_by(Run.repetition_index.asc(), Run.record_index.asc()).all() if b_exp_id else []
    e_runs = db.query(Run).filter_by(experiment_id=e_exp_id).order_by(Run.repetition_index.asc(), Run.record_index.asc()).all() if e_exp_id else []

    from app.api.v1.routes import run_out

    if format == "jsonl":
        lines = [
            json.dumps({"record_type": "group_header", "group": detail}, default=str) + "\n"
        ]
        for r in b_runs:
            lines.append(json.dumps({"record_type": "baseline_run", "condition": "baseline", **run_out(r)}, default=str) + "\n")
        for r in e_runs:
            lines.append(json.dumps({"record_type": "egal_run", "condition": "egal", **run_out(r)}, default=str) + "\n")
        content = "".join(lines)
        media = "application/x-ndjson"
    else:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow([
            "group_id", "condition", "experiment_id", "repetition_index", "run_id",
            "record_index", "status", "execution_duration_ms", "output", "error"
        ])
        for r in b_runs:
            writer.writerow([
                group_id, "baseline", b_exp_id, r.repetition_index or 1, r.id,
                r.record_index, r.status, r.execution_duration_ms, json.dumps(r.output), json.dumps(r.error)
            ])
        for r in e_runs:
            writer.writerow([
                group_id, "egal", e_exp_id, r.repetition_index or 1, r.id,
                r.record_index, r.status, r.execution_duration_ms, json.dumps(r.output), json.dumps(r.error)
            ])
        content = buf.getvalue()
        media = "text/csv"

    filename = f"{group_id}.{format}"
    return content, media, filename
