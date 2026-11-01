"""Analysis Dashboard Service for Research Arena.
Provides a read-only analytics layer over persisted experiments, runs, and evaluations.
Never reruns agents, calls LLMs, alters data, or invents synthetic results.
Reuses existing research-metrics-v1 and evaluation engine definitions.
"""
from datetime import datetime
from pathlib import Path
from typing import Any
from fastapi import HTTPException
from sqlalchemy.orm import Session

from app.models.entities import (
    Dataset,
    DatasetSnapshot,
    Experiment,
    Run,
    Evaluation,
    RunEvaluation,
    ProviderConfiguration,
    AgentRegistration,
)
from app.services.datasets import _records, uid
from app.services.evaluation import (
    calculate_metrics,
    _metric,
    METRIC_DEFINITION_VERSION,
)
from app.schemas.analysis import AnalysisFilterRequest


def _resolve_model(exp: Experiment, db: Session) -> str:
    if getattr(exp, "model", None):
        return str(exp.model)
    cfg = exp.agent_configuration_snapshot or {}
    if isinstance(cfg, dict):
        if cfg.get("model_override"):
            return str(cfg["model_override"])
        if cfg.get("model"):
            return str(cfg["model"])
    pm = exp.provider_metadata_snapshot or {}
    if isinstance(pm, dict):
        if pm.get("model"):
            return str(pm["model"])
        if pm.get("default_model"):
            return str(pm["default_model"])
    prov = db.get(ProviderConfiguration, exp.provider_id)
    if prov and prov.model:
        return prov.model
    return "unknown"


def _determine_condition(agent_id: str) -> str:
    if not agent_id:
        return "baseline"
    if "egal" in agent_id.lower():
        return "egal"
    return "baseline"


def _calculate_delta(
    egal_val: float | int | None,
    baseline_val: float | int | None,
    higher_is_better: bool = True,
) -> dict[str, Any]:
    interpretation = "higher_is_better" if higher_is_better else "lower_is_better"
    if egal_val is None or baseline_val is None:
        return {
            "value": None,
            "delta": None,
            "baseline": baseline_val,
            "egal": egal_val,
            "direction": "not_assessable",
            "interpretation": interpretation,
            "higher_is_better": higher_is_better,
            "is_improvement": None,
            "label": "Not Assessable",
        }
    diff = round(float(egal_val) - float(baseline_val), 4)
    if diff == 0.0:
        direction = "unchanged"
        label = "Equal / Unchanged"
        is_improvement = None
    elif (diff > 0.0 and higher_is_better) or (diff < 0.0 and not higher_is_better):
        direction = "improved"
        label = "Improved"
        is_improvement = True
    else:
        direction = "regressed"
        label = "Regressed"
        is_improvement = False
    return {
        "value": diff,
        "delta": diff,
        "baseline": baseline_val,
        "egal": egal_val,
        "direction": direction,
        "interpretation": interpretation,
        "higher_is_better": higher_is_better,
        "is_improvement": is_improvement,
        "label": label,
    }


def get_analysis_options(db: Session) -> dict[str, Any]:
    """Returns available analysis dimensions based ONLY on actual persisted data."""
    snapshots = db.query(DatasetSnapshot).order_by(DatasetSnapshot.created_at.desc()).all()
    datasets_map = {}
    for s in snapshots:
        ds = db.get(Dataset, s.dataset_id)
        if ds and ds.id not in datasets_map:
            datasets_map[ds.id] = {
                "id": ds.id,
                "name": ds.display_name,
                "original_filename": ds.original_filename,
                "format": ds.format,
            }

    experiments = db.query(Experiment).order_by(Experiment.created_at.desc()).all()
    providers_map = {}
    models_set = set()
    agents_map = {}
    conditions_set = set()
    exp_list = []

    for e in experiments:
        model = _resolve_model(e, db)
        condition = _determine_condition(e.agent_id)
        models_set.add(model)
        conditions_set.add(condition)

        if e.provider_id not in providers_map:
            prov = db.get(ProviderConfiguration, e.provider_id)
            providers_map[e.provider_id] = {
                "id": e.provider_id,
                "display_name": prov.display_name if prov else e.provider_id,
            }

        if e.agent_id not in agents_map:
            agent_reg = db.get(AgentRegistration, e.agent_id)
            agents_map[e.agent_id] = {
                "id": e.agent_id,
                "display_name": agent_reg.display_name if agent_reg else e.agent_id,
                "version": e.agent_version or "unknown",
            }

        exp_list.append({
            "id": e.id,
            "name": e.name,
            "dataset_snapshot_id": e.dataset_snapshot_id,
            "agent_id": e.agent_id,
            "provider_id": e.provider_id,
            "model": model,
            "condition": condition,
            "status": e.status,
            "created_at": e.created_at.isoformat() if e.created_at else None,
        })

    # For selection UX, include active providers and agents so researchers can configure filters
    for prov in db.query(ProviderConfiguration).filter_by(active=True).all():
        if prov.id not in providers_map:
            providers_map[prov.id] = {
                "id": prov.id,
                "display_name": prov.display_name,
            }
        if prov.model:
            models_set.add(prov.model)

    try:
        from app.integrations.registry import list_agent_metadata
        for ag in list_agent_metadata(db):
            aid = ag.get("id")
            if aid and aid not in agents_map:
                agents_map[aid] = {
                    "id": aid,
                    "display_name": ag.get("name") or aid,
                    "version": ag.get("version", "unknown"),
                }
    except Exception:
        pass

    snapshot_list = [
        {
            "id": s.id,
            "dataset_id": s.dataset_id,
            "fingerprint": s.fingerprint,
            "created_at": s.created_at.isoformat() if s.created_at else None,
        }
        for s in snapshots
    ]

    return {
        "datasets": list(datasets_map.values()),
        "dataset_snapshots": snapshot_list,
        "providers": list(providers_map.values()),
        "models": sorted(list(models_set)),
        "agents": list(agents_map.values()),
        "experiments": exp_list,
        "conditions": sorted(list(conditions_set)) if conditions_set else ["baseline", "egal"],
    }


def generate_analysis_report(db: Session, req: AnalysisFilterRequest) -> dict[str, Any]:
    """Generates a complete research analysis report over persisted results."""
    # 1. Dataset Snapshot Validation
    snapshot = db.get(DatasetSnapshot, req.dataset_snapshot_id)
    if not snapshot:
        raise HTTPException(
            status_code=404,
            detail={
                "code": "DATASET_SNAPSHOT_NOT_FOUND",
                "message": f"Dataset snapshot '{req.dataset_snapshot_id}' not found",
            },
        )
    dataset = db.get(Dataset, snapshot.dataset_id)

    # 2. Extract scenarios from snapshot file
    scenarios: list[dict[str, Any]] = []
    snapshot_path = Path(snapshot.storage_path)
    fmt = snapshot_path.suffix.lstrip(".").lower()
    if snapshot_path.exists():
        try:
            for idx, item in _records(snapshot_path, fmt):
                rec_idx = idx - 1 if fmt == "jsonl" else idx
                scenarios.append({
                    "record_index": rec_idx,
                    "scenario_id": item.get("scenario_id", f"SCENARIO-{rec_idx}"),
                    "category": (item.get("category") or "normal").lower(),
                    "ground_truth": item.get("ground_truth"),
                })
        except Exception:
            scenarios = []

    normal_scenarios = sum(1 for s in scenarios if s["category"] == "normal")
    ambiguous_scenarios = sum(1 for s in scenarios if s["category"] == "ambiguous")
    failure_scenarios = sum(1 for s in scenarios if s["category"] == "failure")
    total_scenarios = len(scenarios)
    expected_scenarios = [(s["scenario_id"], s["category"]) for s in scenarios]

    # 3. Snapshot Mismatch Protection
    if req.experiment_ids:
        for exp_id in req.experiment_ids:
            exp_check = db.get(Experiment, exp_id)
            if not exp_check:
                raise HTTPException(
                    status_code=404,
                    detail={
                        "code": "EXPERIMENT_NOT_FOUND",
                        "message": f"Experiment '{exp_id}' not found",
                    },
                )
            if exp_check.dataset_snapshot_id != req.dataset_snapshot_id:
                raise HTTPException(
                    status_code=400,
                    detail={
                        "code": "DATASET_SNAPSHOT_MISMATCH",
                        "message": (
                            f"Experiment '{exp_id}' was executed on snapshot "
                            f"'{exp_check.dataset_snapshot_id}', not '{req.dataset_snapshot_id}'"
                        ),
                    },
                )

    # 4. Filter Candidate Experiments
    query = db.query(Experiment).filter_by(dataset_snapshot_id=req.dataset_snapshot_id)
    if req.experiment_ids:
        query = query.filter(Experiment.id.in_(req.experiment_ids))
    if req.provider_id:
        query = query.filter(Experiment.provider_id == req.provider_id)
    if req.agent_ids:
        query = query.filter(Experiment.agent_id.in_(req.agent_ids))

    all_exps = query.order_by(Experiment.created_at.asc()).all()
    if req.model_name:
        all_exps = [e for e in all_exps if _resolve_model(e, db) == req.model_name]

    # 5. Gather Runs and Evaluations
    exp_data = []
    all_runs: list[Run] = []
    all_run_evals: list[RunEvaluation] = []
    total_expected_runs = 0

    for exp in all_exps:
        runs = db.query(Run).filter_by(experiment_id=exp.id).order_by(Run.record_index).all()
        all_runs.extend(runs)

        ev = (
            db.query(Evaluation)
            .filter_by(experiment_id=exp.id, status="completed")
            .order_by(Evaluation.created_at.desc())
            .first()
        )
        run_evals = []
        if ev:
            run_evals = db.query(RunEvaluation).filter_by(evaluation_id=ev.id).all()
            all_run_evals.extend(run_evals)

        expected_count = (
            ev.expected_run_count
            if (ev and ev.expected_run_count > 0)
            else (len(runs) if len(runs) > 0 else total_scenarios)
        )
        total_expected_runs += expected_count

        exp_data.append({
            "experiment": exp,
            "model": _resolve_model(exp, db),
            "condition": _determine_condition(exp.agent_id),
            "runs": runs,
            "evaluation": ev,
            "run_evaluations": run_evals,
            "expected_runs": expected_count,
        })

    # 6. Calculate Coverage
    actual_runs_count = len(all_runs)
    completed_runs_count = sum(1 for r in all_runs if r.status == "completed")
    failed_runs_count = sum(1 for r in all_runs if r.status == "failed")
    missing_runs_count = max(0, total_expected_runs - actual_runs_count)

    if total_expected_runs > 0:
        coverage_pct = round((completed_runs_count / total_expected_runs) * 100, 2)
    else:
        coverage_pct = 0.0

    if completed_runs_count == 0 or total_expected_runs == 0:
        coverage_status = "insufficient_data"
        is_preliminary = True
    elif (
        completed_runs_count == total_expected_runs
        and failed_runs_count == 0
        and missing_runs_count == 0
    ):
        coverage_status = "complete"
        is_preliminary = False
    else:
        coverage_status = "partial"
        is_preliminary = True

    eval_status_str = "COMPLETED" if coverage_status == "complete" else (
        "INSUFFICIENT_DATA" if coverage_status == "insufficient_data" else "INCOMPLETE"
    )

    # 7. Model Comparison Table
    model_comparison = []
    for item in exp_data:
        exp = item["experiment"]
        ev = item["evaluation"]
        runs = item["runs"]
        comp = sum(1 for r in runs if r.status == "completed")
        exp_expected = item["expected_runs"]

        if ev and ev.metrics:
            tc = ev.metrics.get("task_completion_rate", {}).get("percentage")
            ua = ev.metrics.get("unsupported_action_rate", {}).get("percentage")
            rec = ev.metrics.get("recovery_rate", {}).get("percentage")
            cons = ev.metrics.get("consistency_rate", {}).get("percentage")
            fs_cnt = ev.metrics.get("false_success_rate", {}).get("numerator", 0)
            fs_rate = ev.metrics.get("false_success_rate", {}).get("percentage")
            has_ev = True
        else:
            tc = ua = rec = cons = fs_rate = None
            fs_cnt = 0
            has_ev = False

        # If consistency is None on single evaluation, check if a ConsistencyAggregation exists for this evaluation
        if cons is None and ev:
            try:
                from app.models.entities import ConsistencyAggregation
                for ca in db.query(ConsistencyAggregation).all():
                    if ev.id in (ca.selected_evaluation_ids or []):
                        cons = ca.consistency_rate
                        break
            except Exception:
                pass

        status_str = "complete" if comp == exp_expected and exp_expected > 0 else (
            "insufficient_data" if comp == 0 else "partial"
        )

        model_comparison.append({
            "experiment_id": exp.id,
            "provider": exp.provider_id,
            "model": item["model"],
            "agent": exp.agent_id,
            "agent_version": exp.agent_version or "unknown",
            "condition": item["condition"],
            "task_completion_rate": tc,
            "unsupported_action_rate": ua,
            "recovery_rate": rec,
            "consistency_rate": cons,
            "false_success_count": fs_cnt,
            "false_success_rate": fs_rate,
            "completed_runs": comp,
            "expected_runs": exp_expected,
            "status": status_str,
            "has_evaluation": has_ev,
        })

    # 8. Baseline vs EGAL Comparison
    comparisons = []
    # Group by (provider, model)
    by_provider_model: dict[tuple[str, str], dict[str, Any]] = {}
    for mc in model_comparison:
        key = (mc["provider"], mc["model"])
        if key not in by_provider_model:
            by_provider_model[key] = {}
        by_provider_model[key][mc["condition"]] = mc

    for (prov, mdl), conds in by_provider_model.items():
        if "baseline" in conds and "egal" in conds:
            b = conds["baseline"]
            e = conds["egal"]
            if b["has_evaluation"] and e["has_evaluation"]:
                delta_dict = {
                    "task_completion_rate": _calculate_delta(
                        e["task_completion_rate"], b["task_completion_rate"], higher_is_better=True
                    ),
                    "unsupported_action_rate": _calculate_delta(
                        e["unsupported_action_rate"], b["unsupported_action_rate"], higher_is_better=False
                    ),
                    "recovery_rate": _calculate_delta(
                        e["recovery_rate"], b["recovery_rate"], higher_is_better=True
                    ),
                    "consistency_rate": _calculate_delta(
                        e["consistency_rate"], b["consistency_rate"], higher_is_better=True
                    ),
                    "false_success_count": _calculate_delta(
                        e["false_success_count"], b["false_success_count"], higher_is_better=False
                    ),
                    "false_success_rate": _calculate_delta(
                        e["false_success_rate"], b["false_success_rate"], higher_is_better=False
                    ),
                }
                comparisons.append({
                    "model": mdl,
                    "provider": prov,
                    "baseline": b,
                    "egal": e,
                    "delta": delta_dict,
                })

    baseline_vs_egal = {
        "available": len(comparisons) > 0,
        "comparisons": comparisons,
    }

    # 9. Category Breakdown
    category_breakdown = []
    for cat in ["normal", "ambiguous", "failure"]:
        cat_scenarios_count = sum(1 for s in scenarios if s["category"] == cat)
        cat_evals = [r for r in all_run_evals if r.category == cat]
        cat_runs_count = len(cat_evals)
        cat_completed = sum(1 for r in cat_evals if r.execution_status == "completed")
        cat_failed = sum(1 for r in cat_evals if r.execution_status != "completed")

        item_cat: dict[str, Any] = {
            "category": cat,
            "total_scenarios": cat_scenarios_count,
            "runs": cat_runs_count,
            "completed": cat_completed,
            "failed": cat_failed,
        }

        if cat == "normal":
            task_assessed = [
                r for r in cat_evals
                if (r.task_completion or {}).get("status") in {"pass", "fail"}
            ]
            if task_assessed:
                passes = sum(
                    1 for r in task_assessed
                    if (r.task_completion or {}).get("status") == "pass"
                )
                item_cat["task_completion_rate"] = round(passes / len(task_assessed) * 100, 2)
            else:
                item_cat["task_completion_rate"] = None
        elif cat == "ambiguous":
            ua_assessed = [
                r for r in cat_evals
                if (r.unsupported_action or {}).get("assessment_status") == "assessed"
            ]
            if ua_assessed:
                ua_violations = sum(
                    1 for r in ua_assessed
                    if (r.unsupported_action or {}).get("present") is True
                )
                item_cat["unsupported_action_rate"] = round(ua_violations / len(ua_assessed) * 100, 2)
            else:
                item_cat["unsupported_action_rate"] = None
        elif cat == "failure":
            recoverable = [
                r for r in cat_evals
                if (r.recovery or {}).get("status") in {"recovered", "unrecovered"}
            ]
            if recoverable:
                rec_cnt = sum(
                    1 for r in recoverable
                    if (r.recovery or {}).get("status") == "recovered"
                )
                item_cat["recovery_rate"] = round(rec_cnt / len(recoverable) * 100, 2)
            else:
                item_cat["recovery_rate"] = None

            item_cat["false_success_count"] = sum(
                1 for r in cat_evals
                if (r.false_success or {}).get("is_false_success") is True
                or (r.false_success or {}).get("status") == "fail"
            )

        category_breakdown.append(item_cat)

    # 10. Scenario Breakdown Table
    scenario_breakdown = []
    for sc in scenarios:
        sc_id = sc["scenario_id"]
        sc_cat = sc["category"]
        sc_evals = [r for r in all_run_evals if r.scenario_id == sc_id]
        sc_runs_count = len(sc_evals)
        sc_completed = sum(1 for r in sc_evals if r.execution_status == "completed")
        sc_failed = sum(1 for r in sc_evals if r.execution_status != "completed")

        if sc_cat == "normal":
            passes = sum(1 for r in sc_evals if (r.task_completion or {}).get("status") == "pass")
            fails = sum(1 for r in sc_evals if (r.task_completion or {}).get("status") == "fail")
            if sc_evals:
                st = "pass" if passes > 0 and fails == 0 else ("fail" if fails > 0 else "requires_review")
            else:
                st = "unscored"
            tc_dict = {"status": st, "pass_count": passes, "fail_count": fails}
        else:
            tc_dict = {"status": "not_applicable"}

        if sc_cat == "ambiguous":
            violations = sum(1 for r in sc_evals if (r.unsupported_action or {}).get("present") is True)
            ua_dict = {
                "status": "assessed" if sc_evals else "unscored",
                "present": violations > 0 if sc_evals else None,
                "violation_count": violations,
            }
        else:
            ua_dict = {"status": "not_applicable", "present": None}

        if sc_cat == "failure":
            rec_cnt = sum(1 for r in sc_evals if (r.recovery or {}).get("status") == "recovered")
            unrec_cnt = sum(1 for r in sc_evals if (r.recovery or {}).get("status") == "unrecovered")
            na_cnt = sum(1 for r in sc_evals if (r.recovery or {}).get("status") == "not_applicable")
            if rec_cnt > 0 and unrec_cnt == 0:
                rec_status = "recovered"
            elif unrec_cnt > 0:
                rec_status = "unrecovered"
            elif na_cnt > 0:
                rec_status = "not_applicable"
            else:
                rec_status = "unscored" if not sc_evals else "not_applicable"
            rec_dict = {"status": rec_status, "recovered_count": rec_cnt, "unrecovered_count": unrec_cnt}
        else:
            rec_dict = {"status": "not_applicable"}

        fs_count = sum(
            1 for r in sc_evals
            if (r.false_success or {}).get("is_false_success") is True
            or (r.false_success or {}).get("status") == "fail"
        )
        fs_dict = {"count": fs_count, "is_false_success": fs_count > 0}

        completed_sc_evals = [r for r in sc_evals if r.execution_status == "completed"]
        if len(completed_sc_evals) >= 2:
            sigs = {
                (
                    r.execution_status,
                    tuple(sorted((getattr(r, "decision_signature", {}) or {}).items())),
                    (r.task_completion or {}).get("status"),
                    (getattr(r, "unsupported_action", {}) or {}).get("present"),
                    (getattr(r, "recovery", {}) or {}).get("status"),
                )
                for r in completed_sc_evals
            }
            consistency_val = len(sigs) == 1
        else:
            consistency_val = None

        scenario_breakdown.append({
            "scenario_id": sc_id,
            "category": sc_cat,
            "repetitions": sc_runs_count,
            "completed": sc_completed,
            "failed": sc_failed,
            "task_completion": tc_dict,
            "unsupported_action": ua_dict,
            "recovery": rec_dict,
            "false_success": fs_dict,
            "consistency": consistency_val,
        })

    # 11. EGAL-Specific Diagnostics
    has_egal_experiment = any(item["condition"] == "egal" for item in exp_data)
    if has_egal_experiment:
        egal_runs = [
            r for item in exp_data if item["condition"] == "egal" for r in item["runs"]
        ]
        completed_egal_runs = [r for r in egal_runs if r.status == "completed"]
        egal_evals = [
            r for item in exp_data if item["condition"] == "egal" for r in item["run_evaluations"]
        ]

        abstain_count = 0
        correction_count = 0
        evidence_suff_count = 0
        evidence_insuff_count = 0

        for r in completed_egal_runs:
            out = r.normalized_output or {}
            rec = (out.get("recommendation") or "").strip().upper()
            ab_status = (
                out.get("abstention", {}).get("status")
                if isinstance(out.get("abstention"), dict)
                else None
            )
            if rec == "ABSTAIN" or ab_status == "abstained":
                abstain_count += 1

            audit = out.get("audit") or {}
            if isinstance(audit, dict):
                corr = audit.get("correction") or {}
                if isinstance(corr, dict) and corr.get("executed") is True:
                    correction_count += 1

            suff = out.get("final_evidence_sufficiency") or {}
            if isinstance(suff, dict):
                st = suff.get("status")
                if st == "sufficient":
                    evidence_suff_count += 1
                elif st == "insufficient":
                    evidence_insuff_count += 1

        contradicted_claim_count = 0
        unsupported_claim_count = 0
        for rev in egal_evals:
            for claim in rev.claim_assessments or []:
                ast = claim.get("assessment_status")
                if ast == "contradiction":
                    contradicted_claim_count += 1
                elif ast in {"unsupported_claim", "unsupported"}:
                    unsupported_claim_count += 1

        c_egal = len(completed_egal_runs)
        egal_analysis = {
            "available": True,
            "abstain_count": abstain_count,
            "abstain_rate": round(abstain_count / c_egal * 100, 2) if c_egal else 0.0,
            "correction_executed_count": correction_count,
            "correction_rate": round(correction_count / c_egal * 100, 2) if c_egal else 0.0,
            "evidence_sufficient_count": evidence_suff_count,
            "evidence_insufficient_count": evidence_insuff_count,
            "contradicted_claim_count": contradicted_claim_count,
            "unsupported_claim_count": unsupported_claim_count,
        }
    else:
        egal_analysis = {
            "available": False,
        }

    # 12. Recommendation Distribution
    recommendation_distribution = []
    for item in exp_data:
        exp = item["experiment"]
        condition = item["condition"]
        comp_runs = [r for r in item["runs"] if r.status == "completed"]

        buy = 0
        hold = 0
        sell = 0
        abstain = 0

        for r in comp_runs:
            out = r.normalized_output or {}
            rec = (out.get("recommendation") or "").strip().upper()
            if condition == "egal" and rec == "ABSTAIN":
                abstain += 1
            elif rec == "BUY":
                buy += 1
            elif rec == "SELL":
                sell += 1
            elif rec == "HOLD":
                hold += 1

        recommendation_distribution.append({
            "provider": exp.provider_id,
            "model": item["model"],
            "agent": exp.agent_id,
            "condition": condition,
            "buy": buy,
            "hold": hold,
            "sell": sell,
            "abstain": abstain,
            "total": buy + hold + sell + abstain,
        })

    # 13. Primary Metrics (Overall Report Level)
    if all_run_evals:
        primary_metrics = calculate_metrics(all_run_evals, expected_scenarios)
    elif len(exp_data) == 1 and exp_data[0]["evaluation"] and exp_data[0]["evaluation"].metrics:
        primary_metrics = exp_data[0]["evaluation"].metrics
    else:
        primary_metrics = {
            "task_completion_rate": _metric("task_completion_rate", 0, 0),
            "unsupported_action_rate": _metric("unsupported_action_rate", 0, 0),
            "recovery_rate": _metric("recovery_rate", 0, 0),
            "consistency_rate": _metric("consistency_rate", 0, 0),
            "false_success_rate": _metric("false_success_rate", 0, 0),
        }

    # 14. Chart Data Generation (10 Structured Charts)
    charts: dict[str, Any] = {}

    # Chart 1: Primary metric comparison across models
    c1_models = [
        f"{m['provider']} / {m['model']} ({m['condition']})"
        for m in model_comparison if m["has_evaluation"]
    ]
    if c1_models:
        charts["chart_1_primary_metrics"] = {
            "chart_id": "chart_1_primary_metrics",
            "title": "Primary Metric Comparison Across Models",
            "chart_type": "grouped_bar",
            "categories": c1_models,
            "series": [
                {
                    "name": "Task Completion Rate",
                    "data": [m["task_completion_rate"] for m in model_comparison if m["has_evaluation"]],
                },
                {
                    "name": "Unsupported Action Rate",
                    "data": [m["unsupported_action_rate"] for m in model_comparison if m["has_evaluation"]],
                },
                {
                    "name": "Recovery Rate",
                    "data": [m["recovery_rate"] for m in model_comparison if m["has_evaluation"]],
                },
                {
                    "name": "Consistency Rate",
                    "data": [m["consistency_rate"] for m in model_comparison if m["has_evaluation"]],
                },
            ],
            "available": True,
        }
    else:
        charts["chart_1_primary_metrics"] = {"available": False}

    # Chart 2: Baseline vs EGAL comparison
    if baseline_vs_egal["available"]:
        charts["chart_2_baseline_vs_egal"] = {
            "chart_id": "chart_2_baseline_vs_egal",
            "title": "Baseline vs EGAL Metric Deltas",
            "chart_type": "delta_bar",
            "comparisons": baseline_vs_egal["comparisons"],
            "available": True,
        }
    else:
        charts["chart_2_baseline_vs_egal"] = {"available": False}

    # Chart 3: Unsupported Action Rate by model
    ua_data = [
        {"model": f"{m['provider']} / {m['model']} ({m['condition']})", "value": m["unsupported_action_rate"]}
        for m in model_comparison if m["has_evaluation"] and m["unsupported_action_rate"] is not None
    ]
    charts["chart_3_unsupported_action_rate"] = {
        "chart_id": "chart_3_unsupported_action_rate",
        "title": "Unsupported Action Rate by Model",
        "chart_type": "bar",
        "data": ua_data,
        "available": len(ua_data) > 0,
    }

    # Chart 4: Task Completion Rate by model
    tc_data = [
        {"model": f"{m['provider']} / {m['model']} ({m['condition']})", "value": m["task_completion_rate"]}
        for m in model_comparison if m["has_evaluation"] and m["task_completion_rate"] is not None
    ]
    charts["chart_4_task_completion_rate"] = {
        "chart_id": "chart_4_task_completion_rate",
        "title": "Task Completion Rate by Model",
        "chart_type": "bar",
        "data": tc_data,
        "available": len(tc_data) > 0,
    }

    # Chart 5: Recovery Rate by model
    rec_data = [
        {"model": f"{m['provider']} / {m['model']} ({m['condition']})", "value": m["recovery_rate"]}
        for m in model_comparison if m["has_evaluation"] and m["recovery_rate"] is not None
    ]
    charts["chart_5_recovery_rate"] = {
        "chart_id": "chart_5_recovery_rate",
        "title": "Recovery Rate by Model",
        "chart_type": "bar",
        "data": rec_data,
        "available": len(rec_data) > 0,
    }

    # Chart 6: Consistency Rate by model
    cons_data = [
        {"model": f"{m['provider']} / {m['model']} ({m['condition']})", "value": m["consistency_rate"]}
        for m in model_comparison if m["has_evaluation"] and m["consistency_rate"] is not None
    ]
    charts["chart_6_consistency_rate"] = {
        "chart_id": "chart_6_consistency_rate",
        "title": "Consistency Rate by Model",
        "chart_type": "bar",
        "data": cons_data,
        "available": len(cons_data) > 0,
    }

    # Chart 7: False Success by model
    fs_data = [
        {"model": f"{m['provider']} / {m['model']} ({m['condition']})", "count": m["false_success_count"], "rate": m["false_success_rate"]}
        for m in model_comparison if m["has_evaluation"]
    ]
    charts["chart_7_false_success"] = {
        "chart_id": "chart_7_false_success",
        "title": "False Success by Model",
        "chart_type": "bar",
        "data": fs_data,
        "available": len(fs_data) > 0,
    }

    # Chart 8: Scenario category performance
    charts["chart_8_scenario_category_performance"] = {
        "chart_id": "chart_8_scenario_category_performance",
        "title": "Scenario Category Performance",
        "chart_type": "table_bar",
        "data": category_breakdown,
        "available": len(all_run_evals) > 0,
    }

    # Chart 9: Recommendation distribution
    charts["chart_9_recommendation_distribution"] = {
        "chart_id": "chart_9_recommendation_distribution",
        "title": "Recommendation Distribution (BUY / HOLD / SELL / ABSTAIN)",
        "chart_type": "stacked_bar",
        "data": recommendation_distribution,
        "available": any(r["total"] > 0 for r in recommendation_distribution),
    }

    # Chart 10: EGAL abstention/correction distribution
    if egal_analysis.get("available") and completed_runs_count > 0:
        charts["chart_10_egal_diagnostics"] = {
            "chart_id": "chart_10_egal_diagnostics",
            "title": "EGAL Abstention & Correction Diagnostics",
            "chart_type": "summary_cards",
            "data": egal_analysis,
            "available": True,
        }
    else:
        charts["chart_10_egal_diagnostics"] = {"available": False}

    # 15. Reproducibility & Research Metadata
    model_identities = [
        {
            "provider": item["experiment"].provider_id,
            "model_name": item["model"],
            "agent_id": item["experiment"].agent_id,
            "agent_version": item["experiment"].agent_version or "unknown",
            "condition": item["condition"],
        }
        for item in exp_data
    ]

    research_metadata = {
        "dataset_snapshot_id": snapshot.id,
        "dataset_fingerprint": snapshot.fingerprint,
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "experiment_ids": [item["experiment"].id for item in exp_data],
        "model_identities": model_identities,
        "agent_identities": sorted(list({item["experiment"].agent_id for item in exp_data})),
        "generated_at": datetime.utcnow().isoformat(),
    }

    # 16. Assemble Final Response
    return {
        "report_metadata": {
            "report_id": uid("rep"),
            "created_at": datetime.utcnow().isoformat(),
            "schema_version": "1.0",
            "status": coverage_status,
            "is_preliminary": is_preliminary,
            "filter_applied": {
                "dataset_snapshot_id": req.dataset_snapshot_id,
                "model_name": req.model_name,
                "provider_id": req.provider_id,
                "agent_ids": req.agent_ids,
                "experiment_ids": req.experiment_ids,
            },
        },
        "dataset": {
            "id": dataset.id if dataset else snapshot.dataset_id,
            "name": dataset.display_name if dataset else "Unknown Dataset",
            "version": getattr(dataset, "version", "1.0") if dataset else "1.0",
            "snapshot_id": snapshot.id,
            "fingerprint": snapshot.fingerprint,
            "total_scenarios": total_scenarios,
            "normal_scenarios": normal_scenarios,
            "ambiguous_scenarios": ambiguous_scenarios,
            "failure_scenarios": failure_scenarios,
        },
        "coverage": {
            "expected_runs": total_expected_runs,
            "actual_runs": actual_runs_count,
            "completed_runs": completed_runs_count,
            "failed_runs": failed_runs_count,
            "missing_runs": missing_runs_count,
            "coverage_percentage": coverage_pct,
            "status": coverage_status,
            "evaluation_status": eval_status_str,
            "is_preliminary": is_preliminary,
        },
        "summary": {
            "total_scenarios": total_scenarios,
            "total_experiments": len(exp_data),
            "total_models": len({(item["experiment"].provider_id, item["model"]) for item in exp_data}),
            "total_runs": actual_runs_count,
            "completed_runs": completed_runs_count,
            "failed_runs": failed_runs_count,
            "coverage_percentage": coverage_pct,
            "status": coverage_status,
            "note": "Complete research report" if not is_preliminary else "Partial / preliminary analysis",
        },
        "primary_metrics": primary_metrics,
        "category_breakdown": category_breakdown,
        "scenario_breakdown": scenario_breakdown,
        "model_comparison": model_comparison,
        "baseline_vs_egal": baseline_vs_egal,
        "recommendation_distribution": recommendation_distribution,
        "egal_analysis": egal_analysis,
        "charts": charts,
        "research_metadata": research_metadata,
    }
