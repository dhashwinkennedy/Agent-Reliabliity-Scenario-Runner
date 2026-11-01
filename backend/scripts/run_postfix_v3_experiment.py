"""
Post-Fix V3 5-Repetition Experiment Runner for Baseline vs EGAL
Executes 5 complete repetitions (90 runs each, 180 runs total)
against ollama-kaggle-qwen2.5:7b-instruct on financial_news_dataset_v1_fixed.

Includes:
1. Exact execution of failure_injection schedules (e.g. FAILURE-001 timeout on att 1, success on att 2;
   FAILURE-002 503 on att 1 & 2, success on att 3; FAILURE-003 all 3 fail).
2. Proper recording of attempt history, retries used, and duration.
3. Enhanced EGAL recommendation validation distinguishing factual claims from directional recommendation support.
4. Offline evaluation of each repetition.
5. Cross-repetition consistency rate aggregation across the 6 designated repeatability scenarios.
"""
import sys, os, time, uuid, json, threading
from datetime import datetime
from pathlib import Path

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.session import SessionLocal
from app.models.entities import (
    ExperimentGroup,
    Experiment,
    ExperimentRepetition,
    Run,
    DatasetSnapshot,
    Evaluation,
)
from app.integrations.registry import resolve_agent, providers
from app.services.datasets import _records
from app.services.evaluation import evaluate_experiment
from app.services.consistency import aggregate_consistency, REPEATABILITY_IDS
from app.services.grouping import get_group_detail_service

GROUP_ID = "grp_postfix_v3_comparison"
GROUP_NAME = "POST_FIX_V3_BASELINE_VS_EGAL"
SNAPSHOT_ID = "snap_70818373517c4fdba447caf760732583"
PROVIDER_ID = "m7yd1ohlhj1gp79ju6gxiuaf87au-ickfnb97y"
MODEL_NAME = "qwen2.5:7b-instruct"
REPETITION_COUNT = 5


def safe_str(val):
    if val is None:
        return ""
    s = str(val)
    return s.encode("ascii", "replace").decode("ascii")


def setup_experiment_entities():
    db = SessionLocal()
    try:
        snap = db.get(DatasetSnapshot, SNAPSHOT_ID)
        if not snap:
            raise RuntimeError(f"Snapshot {SNAPSHOT_ID} not found")

        # 1. Experiment Group
        grp = db.get(ExperimentGroup, GROUP_ID)
        if not grp:
            grp = ExperimentGroup(
                id=GROUP_ID,
                name=GROUP_NAME,
                dataset_snapshot_id=SNAPSHOT_ID,
                provider_id=PROVIDER_ID,
                model=MODEL_NAME,
                created_at=datetime.utcnow(),
            )
            db.add(grp)
            db.commit()
            print(f"[SETUP] Created group {GROUP_ID}")
        else:
            print(f"[SETUP] Existing group {GROUP_ID} found")

        # 2. Experiments
        exp_specs = [
            ("exp_postfix_baseline_003", "POST_FIX_V3_BASELINE", "financial_news_analysis"),
            ("exp_postfix_egal_003", "POST_FIX_V3_EGAL", "financial_news_analysis_egal"),
        ]

        fmt = Path(snap.storage_path).suffix.lstrip(".")
        records = [r for _, r in _records(Path(snap.storage_path), fmt)]
        print(f"[SETUP] Loaded {len(records)} scenarios from snapshot.")

        for exp_id, exp_name, agent_id in exp_specs:
            exp = db.get(Experiment, exp_id)
            if not exp:
                agent = resolve_agent(db, agent_id)
                exp = Experiment(
                    id=exp_id,
                    name=exp_name,
                    group_id=GROUP_ID,
                    group_name=GROUP_NAME,
                    dataset_snapshot_id=SNAPSHOT_ID,
                    agent_id=agent_id,
                    agent_version=agent.metadata().get("version", "1.0"),
                    agent_configuration_snapshot={},
                    provider_id=PROVIDER_ID,
                    provider_metadata_snapshot={"model": MODEL_NAME, "id": PROVIDER_ID},
                    model=MODEL_NAME,
                    status="draft",
                    created_at=datetime.utcnow(),
                )
                db.add(exp)
                db.commit()
                print(f"[SETUP] Created experiment {exp_id} ({agent_id})")

            # Create 5 repetitions and runs if not already created
            for rep_idx in range(1, REPETITION_COUNT + 1):
                rep_id = f"rep_{exp_id}_{rep_idx}"
                rep = db.get(ExperimentRepetition, rep_id)
                if not rep:
                    rep = ExperimentRepetition(
                        id=rep_id,
                        experiment_id=exp_id,
                        repetition_index=rep_idx,
                        status="queued",
                        run_count=len(records),
                        completed_run_count=0,
                        failed_run_count=0,
                        created_at=datetime.utcnow(),
                    )
                    db.add(rep)
                    db.flush()

                    runs = []
                    for i, r in enumerate(records):
                        rec_idx = i - 1 if fmt == "jsonl" else i
                        run_id = f"run_{exp_id}_{rep_idx}_{rec_idx:02d}"
                        run = Run(
                            id=run_id,
                            experiment_id=exp_id,
                            repetition_id=rep_id,
                            repetition_index=rep_idx,
                            record_index=rec_idx,
                            status="queued",
                        )
                        runs.append(run)
                    db.add_all(runs)
                    db.commit()
                    print(f"[SETUP] Created Repetition {rep_idx} ({rep_id}) with {len(runs)} runs")
    finally:
        db.close()


def execute_agent_repetition(exp_id, rep_idx):
    db = SessionLocal()
    try:
        exp = db.get(Experiment, exp_id)
        rep_id = f"rep_{exp_id}_{rep_idx}"
        rep = db.get(ExperimentRepetition, rep_id)

        snap = db.get(DatasetSnapshot, exp.dataset_snapshot_id)
        fmt = Path(snap.storage_path).suffix.lstrip(".")
        records = {
            (i - 1 if fmt == "jsonl" else i): r
            for i, r in _records(Path(snap.storage_path), fmt)
        }

        agent = resolve_agent(db, exp.agent_id)
        provider = providers.get(exp.provider_id)
        config = {
            **(exp.agent_configuration_snapshot or {}),
            "provider_id": exp.provider_id,
            "model": exp.model,
            "model_override": exp.model,
        }

        if rep.status == "completed" and rep.completed_run_count + rep.failed_run_count == len(records):
            print(f"[{exp.agent_id} Rep {rep_idx}] Already completed.")
            return

        rep.status = "running"
        rep.started_at = rep.started_at or datetime.utcnow()
        if exp.status in {"draft", "queued"}:
            exp.status = "running"
        db.commit()

        runs = (
            db.query(Run)
            .filter_by(experiment_id=exp_id, repetition_id=rep_id)
            .order_by(Run.record_index.asc())
            .all()
        )

        for run in runs:
            if run.status in {"completed", "failed"} and run.completed_at is not None:
                continue

            rec = records[run.record_index]
            scenario_id = rec.get("scenario_id") or rec.get("input", {}).get("scenario_id") or f"idx_{run.record_index}"
            payload = rec.get("input")

            run.status = "running"
            run.started_at = datetime.utcnow()
            db.commit()

            t0 = time.time()
            try:
                # Check for failure_injection
                meta = rec.get("metadata", {})
                orig = meta.get("original_record", {}) if isinstance(meta, dict) else {}
                failure_injection = orig.get("failure_injection") or (meta.get("failure_injection") if isinstance(meta, dict) else None) or rec.get("failure_injection")
                attempt_schedule = failure_injection.get("attempt_schedule", []) if isinstance(failure_injection, dict) else []

                if attempt_schedule:
                    max_retries = orig.get("max_retries", 2) if isinstance(orig, dict) else 2
                    attempt_history = []
                    final_result = None
                    retries_used = 0

                    for step in attempt_schedule:
                        att_num = step.get("attempt", len(attempt_history) + 1)
                        outcome = step.get("outcome")
                        if outcome == "fail":
                            err_code = step.get("error_code", "SIMULATED_FAILURE")
                            attempt_history.append({
                                "attempt": att_num,
                                "outcome": "fail",
                                "error_code": err_code,
                                "message": f"Injected simulated failure: {err_code}",
                                "timestamp": datetime.utcnow().isoformat(),
                            })
                            retries_used += 1
                            if retries_used > max_retries:
                                break
                        elif outcome == "success":
                            current_payload = dict(payload)
                            if step.get("payload"):
                                if "ml_forecast" in step["payload"] or "model" in step["payload"]:
                                    current_payload["ml_forecast"] = step["payload"]
                                else:
                                    current_payload.update(step["payload"])
                            res = agent.run(current_payload, provider, config)
                            attempt_history.append({
                                "attempt": att_num,
                                "outcome": "success" if res.run_status == "completed" else "fail",
                                "error_code": res.error_code if res.run_status != "completed" else None,
                                "message": res.error_message if res.run_status != "completed" else "Execution succeeded on retry",
                                "execution_duration_ms": res.execution_duration_ms,
                                "timestamp": datetime.utcnow().isoformat(),
                            })
                            if res.run_status == "completed":
                                final_result = res
                                break

                    dur_ms = int((time.time() - t0) * 1000)
                    if final_result and final_result.run_status == "completed":
                        run.status = "completed"
                        run.error = None
                        raw_dict = dict(final_result.raw_output) if isinstance(final_result.raw_output, dict) else {"raw": final_result.raw_output}
                        raw_dict["_attempt_history"] = attempt_history
                        raw_dict["_retries_used"] = len([a for a in attempt_history if a.get("outcome") == "fail"])
                        raw_dict["_recovery_simulated"] = True
                        run.raw_output = raw_dict

                        norm_dict = dict(final_result.normalized_output) if isinstance(final_result.normalized_output, dict) else {}
                        norm_dict["_attempt_history"] = attempt_history
                        norm_dict["_retries_used"] = len([a for a in attempt_history if a.get("outcome") == "fail"])
                        run.normalized_output = norm_dict
                        run.output = norm_dict
                        run.execution_duration_ms = final_result.execution_duration_ms or dur_ms

                        rep.completed_run_count = (rep.completed_run_count or 0) + 1
                        norm = final_result.normalized_output or {}
                        sig_info = f"rec={norm.get('recommendation')}, sent={norm.get('sentiment')}, conf={norm.get('confidence')}, retries={raw_dict['_retries_used']}"
                        print(f"[{exp.agent_id} R{rep_idx}] Run {run.record_index:02d} ({scenario_id}) RECOVERED in {dur_ms/1000:.1f}s | {sig_info}", flush=True)
                    else:
                        run.status = "failed"
                        last_fail = attempt_history[-1] if attempt_history else {}
                        run.error = {
                            "code": last_fail.get("error_code", "RUN_FAILED"),
                            "message": last_fail.get("message", "All scheduled attempts failed"),
                            "attempt_history": attempt_history,
                            "retries_used": max(0, len(attempt_history) - 1),
                        }
                        run.raw_output = {"_attempt_history": attempt_history, "_retries_used": max(0, len(attempt_history) - 1)}
                        run.normalized_output = None
                        run.output = None
                        run.execution_duration_ms = dur_ms
                        rep.failed_run_count = (rep.failed_run_count or 0) + 1
                        print(f"[{exp.agent_id} R{rep_idx}] Run {run.record_index:02d} ({scenario_id}) EXPECTED_FAILURE in {dur_ms/1000:.1f}s | {run.error['code']}", flush=True)
                else:
                    res = agent.run(payload, provider, config)
                    dur_ms = int((time.time() - t0) * 1000)
                    attempt_history = [{
                        "attempt": 1,
                        "outcome": "success" if res.run_status == "completed" else "fail",
                        "error_code": res.error_code if res.run_status != "completed" else None,
                        "message": res.error_message if res.run_status != "completed" else "Completed on initial attempt",
                        "execution_duration_ms": res.execution_duration_ms or dur_ms,
                        "timestamp": datetime.utcnow().isoformat(),
                    }]

                    if res.run_status == "completed":
                        run.status = "completed"
                        run.error = None
                        raw_dict = dict(res.raw_output) if isinstance(res.raw_output, dict) else {"raw": res.raw_output}
                        raw_dict["_attempt_history"] = attempt_history
                        raw_dict["_retries_used"] = 0
                        run.raw_output = raw_dict

                        norm_dict = dict(res.normalized_output) if isinstance(res.normalized_output, dict) else {}
                        norm_dict["_attempt_history"] = attempt_history
                        norm_dict["_retries_used"] = 0
                        run.normalized_output = norm_dict
                        run.output = norm_dict
                        run.execution_duration_ms = res.execution_duration_ms or dur_ms

                        rep.completed_run_count = (rep.completed_run_count or 0) + 1
                        norm = res.normalized_output or {}
                        sig_info = f"rec={norm.get('recommendation')}, sent={norm.get('sentiment')}, conf={norm.get('confidence')}"
                        print(f"[{exp.agent_id} R{rep_idx}] Run {run.record_index:02d} ({scenario_id}) OK in {dur_ms/1000:.1f}s | {sig_info}", flush=True)
                    else:
                        run.status = "failed"
                        run.error = {
                            "code": res.error_code or "RUN_FAILED",
                            "message": res.error_message or "Agent execution failed",
                            "attempt_history": attempt_history,
                            "retries_used": 0,
                        }
                        run.raw_output = {"_attempt_history": attempt_history, "_retries_used": 0}
                        run.normalized_output = None
                        run.output = None
                        run.execution_duration_ms = dur_ms
                        rep.failed_run_count = (rep.failed_run_count or 0) + 1
                        print(f"[{exp.agent_id} R{rep_idx}] Run {run.record_index:02d} ({scenario_id}) FAIL in {dur_ms/1000:.1f}s | {res.error_code}: {safe_str(res.error_message)}", flush=True)

            except Exception as exc:
                dur_ms = int((time.time() - t0) * 1000)
                run.status = "failed"
                run.error = {"code": "RUN_FAILED", "message": str(exc)}
                rep.failed_run_count = (rep.failed_run_count or 0) + 1
                print(f"[{exp.agent_id} R{rep_idx}] Run {run.record_index:02d} ({scenario_id}) EXCEPTION in {dur_ms/1000:.1f}s | {safe_str(exc)}", flush=True)

            run.completed_at = datetime.utcnow()
            db.commit()

        # Repetition finished
        rep.completed_at = datetime.utcnow()
        tot = (rep.completed_run_count or 0) + (rep.failed_run_count or 0)
        if rep.failed_run_count and rep.failed_run_count == tot:
            rep.status = "failed"
        else:
            rep.status = "completed"
        db.commit()

        # Run repetition evaluation
        print(f"[{exp.agent_id} R{rep_idx}] Running offline evaluation for repetition...")
        eval_item = evaluate_experiment(db, exp, force=True, repetition_id=rep_id, repetition_index=rep_idx)
        print(f"[{exp.agent_id} R{rep_idx}] Eval {eval_item.id}: TC={eval_item.metrics.get('task_completion_rate', {}).get('percentage')}%, UA={eval_item.metrics.get('unsupported_action_rate', {}).get('percentage')}%, Recov={eval_item.metrics.get('recovery_rate', {}).get('percentage')}%")
    finally:
        db.close()


def run_full_suite():
    setup_experiment_entities()

    # 1. Execute Baseline Repetitions 1..5
    print("\n" + "="*70)
    print("STARTING BASELINE 5-REPETITION EXECUTION")
    print("="*70)
    for r in range(1, REPETITION_COUNT + 1):
        execute_agent_repetition("exp_postfix_baseline_003", r)

    # 2. Execute EGAL Repetitions 1..5
    print("\n" + "="*70)
    print("STARTING EGAL 5-REPETITION EXECUTION")
    print("="*70)
    for r in range(1, REPETITION_COUNT + 1):
        execute_agent_repetition("exp_postfix_egal_003", r)

    # 3. Post-execution consistency aggregation
    print("\n" + "="*70)
    print("RUNNING CROSS-REPETITION CONSISTENCY AGGREGATION")
    print("="*70)
    db = SessionLocal()
    try:
        # Collect baseline evaluations
        b_evals = (
            db.query(Evaluation)
            .filter_by(experiment_id="exp_postfix_baseline_003", status="completed")
            .order_by(Evaluation.repetition_index.asc())
            .all()
        )
        b_eids = [e.id for e in b_evals]
        print(f"Baseline completed evaluation IDs: {b_eids}")
        if len(b_eids) >= 5:
            b_agg = aggregate_consistency(db, b_eids[:5], persist=True)
            print(f"Baseline Consistency Rate: {b_agg.consistency_rate}% ({b_agg.consistent_group_count}/{b_agg.assessable_group_count})")
        else:
            print(f"Baseline incomplete evaluations: {len(b_eids)}/5")

        # Collect EGAL evaluations
        e_evals = (
            db.query(Evaluation)
            .filter_by(experiment_id="exp_postfix_egal_003", status="completed")
            .order_by(Evaluation.repetition_index.asc())
            .all()
        )
        e_eids = [e.id for e in e_evals]
        print(f"EGAL completed evaluation IDs: {e_eids}")
        if len(e_eids) >= 5:
            e_agg = aggregate_consistency(db, e_eids[:5], persist=True)
            print(f"EGAL Consistency Rate: {e_agg.consistency_rate}% ({e_agg.consistent_group_count}/{e_agg.assessable_group_count})")
        else:
            print(f"EGAL incomplete evaluations: {len(e_eids)}/5")

    finally:
        db.close()


if __name__ == "__main__":
    run_full_suite()
