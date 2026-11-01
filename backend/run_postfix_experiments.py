"""Runner for Post-Fix Baseline vs EGAL Repetitions (Phase I).
Executes 5 complete repetitions for Baseline and 5 complete repetitions for EGAL
against ollama-kaggle-qwen2.5:7b-instruct on financial_news_dataset_v1_fixed.
"""
import time
import uuid
from datetime import datetime
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed

from app.database.session import SessionLocal
from app.models.entities import (
    Experiment,
    ExperimentGroup,
    ExperimentRepetition,
    Run,
    DatasetSnapshot,
    ProviderConfiguration,
)
from app.integrations.registry import resolve_agent, providers
from app.services.datasets import _records
from app.services.evaluation import evaluate_experiment
from app.services.grouping import get_group_detail_service


SNAPSHOT_ID = "snap_70818373517c4fdba447caf760732583"
PROVIDER_ID = "m7yd1ohlhj1gp79ju6gxiuaf87au-ickfnb97y"
MODEL_NAME = "qwen2.5:7b-instruct"
GROUP_ID = "grp_postfix_comparison_001"
GROUP_NAME = "POST_FIX_BASELINE_VS_EGAL_COMPARISON"

BASELINE_EXP_ID = "exp_postfix_baseline_001"
BASELINE_EXP_NAME = "POST_FIX_BASELINE"
BASELINE_AGENT_ID = "financial_news_analysis"

EGAL_EXP_ID = "exp_postfix_egal_001"
EGAL_EXP_NAME = "POST_FIX_EGAL"
EGAL_AGENT_ID = "financial_news_analysis_egal"

PLANNED_REPETITIONS = 5
MAX_WORKERS = 3  # safe concurrency for Ollama endpoint


def get_or_create_group(db):
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
    return grp


def get_or_create_experiment(db, exp_id, exp_name, agent_id):
    exp = db.get(Experiment, exp_id)
    if not exp:
        exp = Experiment(
            id=exp_id,
            name=exp_name,
            group_id=GROUP_ID,
            group_name=GROUP_NAME,
            dataset_snapshot_id=SNAPSHOT_ID,
            agent_id=agent_id,
            provider_id=PROVIDER_ID,
            model=MODEL_NAME,
            status="running",
            input_mapping={},
            created_at=datetime.utcnow(),
        )
        db.add(exp)
        db.commit()
    return exp


def execute_single_run(run_id, exp_id, agent_id, record):
    """Executes a single scenario run in its own thread with a fresh DB session."""
    db = SessionLocal()
    try:
        run = db.get(Run, run_id)
        if not run:
            return None
        run.status = "running"
        run.started_at = datetime.utcnow()
        db.commit()

        payload = record.get("input", {})
        agent = resolve_agent(db, agent_id)
        config = {
            "provider_id": PROVIDER_ID,
            "model_override": MODEL_NAME,
            "model": MODEL_NAME,
        }

        started = time.monotonic()
        result = agent.run(payload, providers.get(PROVIDER_ID), config)
        duration_ms = int((time.monotonic() - started) * 1000)

        run.raw_output = result.raw_output
        run.normalized_output = result.normalized_output
        run.output = result.normalized_output
        run.execution_duration_ms = duration_ms
        run.completed_at = datetime.utcnow()

        if result.run_status == "completed":
            run.status = "completed"
            run.error = None
        else:
            run.status = "failed"
            run.error = {
                "code": result.error_code or "RUN_FAILED",
                "message": result.error_message or "Execution failed",
            }
        db.commit()
        return run.status
    except Exception as exc:
        db.rollback()
        run = db.get(Run, run_id)
        if run:
            run.status = "failed"
            run.error = {"code": "RUN_FAILED", "message": str(exc)}
            run.completed_at = datetime.utcnow()
            db.commit()
        return "failed"
    finally:
        db.close()


def run_repetition(exp_id, agent_id, rep_idx, records_map):
    """Runs a complete 18-scenario repetition for an experiment."""
    db = SessionLocal()
    try:
        exp = db.get(Experiment, exp_id)
        rep_id = f"rep_{exp_id}_{rep_idx}"
        rep = db.get(ExperimentRepetition, rep_id)
        if not rep:
            rep = ExperimentRepetition(
                id=rep_id,
                experiment_id=exp_id,
                repetition_index=rep_idx,
                status="running",
                created_at=datetime.utcnow(),
                started_at=datetime.utcnow(),
                run_count=len(records_map),
                completed_run_count=0,
                failed_run_count=0,
            )
            db.add(rep)
            db.commit()

            # Create 18 runs
            runs = []
            for rec_idx in sorted(records_map.keys()):
                r = Run(
                    id=f"run_{uuid.uuid4().hex}",
                    experiment_id=exp_id,
                    repetition_id=rep_id,
                    repetition_index=rep_idx,
                    record_index=rec_idx,
                    status="queued",
                )
                runs.append(r)
            db.add_all(runs)
            db.commit()

        queued_runs = (
            db.query(Run)
            .filter_by(experiment_id=exp_id, repetition_id=rep_id, status="queued")
            .order_by(Run.record_index)
            .all()
        )
        run_items = [(r.id, r.record_index) for r in queued_runs]
    finally:
        db.close()

    if run_items:
        print(f"[{exp_id}] Repetition {rep_idx}: executing {len(run_items)} runs...")
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            futures = [
                executor.submit(
                    execute_single_run,
                    r_id,
                    exp_id,
                    agent_id,
                    records_map[rec_idx],
                )
                for r_id, rec_idx in run_items
            ]
            for f in as_completed(futures):
                pass

    # Update repetition terminal status and evaluate
    db = SessionLocal()
    try:
        rep = db.get(ExperimentRepetition, rep_id)
        all_rep_runs = db.query(Run).filter_by(experiment_id=exp_id, repetition_id=rep_id).all()
        comp = sum(1 for r in all_rep_runs if r.status == "completed")
        fail = sum(1 for r in all_rep_runs if r.status == "failed")
        rep.completed_run_count = comp
        rep.failed_run_count = fail
        rep.status = "completed" if comp > 0 else "failed"
        rep.completed_at = datetime.utcnow()
        db.commit()

        exp = db.get(Experiment, exp_id)
        print(f"[{exp_id}] Repetition {rep_idx}: evaluating {len(all_rep_runs)} runs...")
        eval_item = evaluate_experiment(
            db,
            exp,
            force=True,
            repetition_id=rep.id,
            repetition_index=rep_idx,
        )
        print(f"[{exp_id}] Repetition {rep_idx}: evaluation {eval_item.id} persisted with status {eval_item.status}")
        return eval_item.id, comp, fail
    finally:
        db.close()


def main():
    print("=== STARTING PHASE I: POST-FIX EXPERIMENTAL RUNS ===")
    t_start = time.time()

    db = SessionLocal()
    get_or_create_group(db)
    exp_b = get_or_create_experiment(db, BASELINE_EXP_ID, BASELINE_EXP_NAME, BASELINE_AGENT_ID)
    exp_e = get_or_create_experiment(db, EGAL_EXP_ID, EGAL_EXP_NAME, EGAL_AGENT_ID)

    snap = db.get(DatasetSnapshot, SNAPSHOT_ID)
    fmt = Path(snap.storage_path).suffix.lstrip(".")
    records_map = {
        (i - 1 if fmt == "jsonl" else i): r
        for i, r in _records(Path(snap.storage_path), fmt)
    }
    db.close()

    print(f"Loaded snapshot {SNAPSHOT_ID} with {len(records_map)} scenarios.")

    # 1. Run 5 Baseline Repetitions
    print("\n--- RUNNING 5 BASELINE REPETITIONS ---")
    b_eval_ids = []
    for rep_i in range(1, PLANNED_REPETITIONS + 1):
        t0 = time.time()
        eid, comp, fail = run_repetition(BASELINE_EXP_ID, BASELINE_AGENT_ID, rep_i, records_map)
        b_eval_ids.append(eid)
        print(f"Baseline Repetition {rep_i} finished in {time.time()-t0:.1f}s (completed={comp}, failed={fail}, eval={eid})")

    # Mark baseline experiment completed
    db = SessionLocal()
    exp_b = db.get(Experiment, BASELINE_EXP_ID)
    exp_b.status = "completed"
    db.commit()
    db.close()

    # 2. Run 5 EGAL Repetitions
    print("\n--- RUNNING 5 EGAL REPETITIONS ---")
    e_eval_ids = []
    for rep_i in range(1, PLANNED_REPETITIONS + 1):
        t0 = time.time()
        eid, comp, fail = run_repetition(EGAL_EXP_ID, EGAL_AGENT_ID, rep_i, records_map)
        e_eval_ids.append(eid)
        print(f"EGAL Repetition {rep_i} finished in {time.time()-t0:.1f}s (completed={comp}, failed={fail}, eval={eid})")

    # Mark EGAL experiment completed
    db = SessionLocal()
    exp_e = db.get(Experiment, EGAL_EXP_ID)
    exp_e.status = "completed"
    db.commit()
    db.close()

    t_total = time.time() - t_start
    print(f"\nAll 10 repetitions completed in {t_total:.1f}s ({t_total/60:.1f} minutes)!")

    # 3. Fetch Group Detail and Consistency Aggregation
    print("\n=== FETCHING FINAL POOLED EXPERIMENT GROUP RESULTS ===")
    db = SessionLocal()
    group_detail = get_group_detail_service(db, GROUP_ID)
    db.close()

    print("\n--- BASELINE POOLED METRICS ---")
    for k, v in group_detail["baseline"]["pooled_metrics"].items():
        print(f"  {k}: {v.get('percentage')}% ({v.get('numerator')}/{v.get('denominator')}, status={v.get('status')})")

    print("\n--- EGAL POOLED METRICS ---")
    for k, v in group_detail["egal"]["pooled_metrics"].items():
        print(f"  {k}: {v.get('percentage')}% ({v.get('numerator')}/{v.get('denominator')}, status={v.get('status')})")

    print("\n--- BASELINE VS EGAL DELTAS ---")
    for k, v in group_detail["comparison"]["deltas"].items():
        print(f"  {k}: delta={v.get('delta')}, dir={v.get('direction')}, label={v.get('label')}")


if __name__ == "__main__":
    main()
