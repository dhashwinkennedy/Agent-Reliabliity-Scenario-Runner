"""
Post-Fix 5-Repetition Experiment Runner for Baseline vs EGAL
Executes 5 complete repetitions (90 runs each, 180 runs total)
against ollama-kaggle-qwen2.5:7b-instruct on financial_news_dataset_v1_fixed.
Evaluates every repetition and calculates the cross-repetition Consistency Rate.
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
from app.services.grouping import get_group_detail_service

GROUP_ID = "grp_postfix_v2_comparison"
GROUP_NAME = "POST_FIX_BASELINE_VS_EGAL_V2"
SNAPSHOT_ID = "snap_70818373517c4fdba447caf760732583"
PROVIDER_ID = "m7yd1ohlhj1gp79ju6gxiuaf87au-ickfnb97y"
MODEL_NAME = "qwen2.5:7b-instruct"
REPETITION_COUNT = 5


def safe_str(val):
    """Safely format string avoiding console encoding issues with special unicode chars."""
    if val is None:
        return ""
    s = str(val)
    return s.encode("ascii", "replace").decode("ascii")


def setup_experiment_entities():
    db = SessionLocal()
    try:
        # Check snapshot
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
            ("exp_postfix_baseline_002", "POST_FIX_BASELINE_V2", "financial_news_analysis"),
            ("exp_postfix_egal_002", "POST_FIX_EGAL_V2", "financial_news_analysis_egal"),
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

        # Check if already completed
        if rep.status == "completed" and rep.completed_run_count == len(records):
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
            if run.status == "completed":
                continue

            rec = records[run.record_index]
            scenario_id = rec.get("scenario_id") or rec.get("input", {}).get("scenario_id") or f"idx_{run.record_index}"
            payload = rec.get("input")

            run.status = "running"
            run.started_at = datetime.utcnow()
            db.commit()

            t0 = time.time()
            try:
                res = agent.run(payload, provider, config)
                t1 = time.time()
                dur_ms = int((t1 - t0) * 1000)

                run.raw_output = res.raw_output
                run.normalized_output = res.normalized_output
                run.execution_duration_ms = res.execution_duration_ms or dur_ms
                run.output = res.normalized_output

                if res.run_status == "completed":
                    run.status = "completed"
                    run.error = None
                    rep.completed_run_count = (rep.completed_run_count or 0) + 1
                    norm = res.normalized_output or {}
                    sig_info = f"rec={norm.get('recommendation')}, sent={norm.get('sentiment')}, conf={norm.get('confidence')}"
                    print(f"[{exp.agent_id} R{rep_idx}] Run {run.record_index:02d} ({scenario_id}) OK in {dur_ms/1000:.1f}s | {sig_info}")
                else:
                    run.status = "failed"
                    run.error = {
                        "code": res.error_code or "RUN_FAILED",
                        "message": res.error_message or "Agent execution failed",
                    }
                    rep.failed_run_count = (rep.failed_run_count or 0) + 1
                    print(f"[{exp.agent_id} R{rep_idx}] Run {run.record_index:02d} ({scenario_id}) FAIL in {dur_ms/1000:.1f}s | {res.error_code}: {safe_str(res.error_message)}")
            except Exception as exc:
                t1 = time.time()
                dur_ms = int((t1 - t0) * 1000)
                run.status = "failed"
                run.error = {"code": "RUN_FAILED", "message": str(exc)}
                rep.failed_run_count = (rep.failed_run_count or 0) + 1
                print(f"[{exp.agent_id} R{rep_idx}] Run {run.record_index:02d} ({scenario_id}) EXCEPTION in {dur_ms/1000:.1f}s | {safe_str(exc)}")

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
        print(f"[{exp.agent_id} R{rep_idx}] Running evaluation for repetition...")
        ev = evaluate_experiment(db, exp, force=True, repetition_id=rep.id, repetition_index=rep.repetition_index)
        m = ev.metrics or {}
        tc = m.get("task_completion_rate", {})
        ua = m.get("unsupported_action_rate", {})
        rec = m.get("recovery_rate", {})
        fs = m.get("false_success_rate", {})
        print(f"[{exp.agent_id} R{rep_idx}] EVAL ID: {ev.id}")
        print(f"    Task Completion: {tc.get('numerator')}/{tc.get('denominator')} ({tc.get('percentage')}%)")
        print(f"    Unsupported Act: {ua.get('numerator')}/{ua.get('denominator')} ({ua.get('percentage')}%)")
        print(f"    Recovery Rate:   {rec.get('numerator')}/{rec.get('denominator')} ({rec.get('percentage')}%)")
        print(f"    False Success:   {fs.get('numerator')}/{fs.get('denominator')} ({fs.get('percentage')}%)")

    finally:
        db.close()


def run_agent_all_repetitions(exp_id):
    print(f"\n>>> Starting all {REPETITION_COUNT} repetitions for {exp_id} <<<")
    for rep_idx in range(1, REPETITION_COUNT + 1):
        execute_agent_repetition(exp_id, rep_idx)
    
    db = SessionLocal()
    try:
        exp = db.get(Experiment, exp_id)
        exp.status = "completed"
        db.commit()
        print(f">>> Experiment {exp_id} marked COMPLETED <<<\n")
    finally:
        db.close()


def main():
    print("=" * 70)
    print("RESEARCH ARENA: POST-FIX 5-REPETITION EXPERIMENT EXECUTION")
    print(f"Dataset Snapshot: {SNAPSHOT_ID}")
    print(f"Provider: {PROVIDER_ID} ({MODEL_NAME})")
    print(f"Group: {GROUP_ID}")
    print("=" * 70)

    setup_experiment_entities()

    t_start = time.time()

    # Run Baseline and EGAL concurrently
    t_baseline = threading.Thread(target=run_agent_all_repetitions, args=("exp_postfix_baseline_002",))
    t_egal = threading.Thread(target=run_agent_all_repetitions, args=("exp_postfix_egal_002",))

    t_baseline.start()
    t_egal.start()

    t_baseline.join()
    t_egal.join()

    total_duration = time.time() - t_start
    print(f"\nAll repetitions finished in {total_duration/60:.2f} minutes.")

    # Group evaluation
    print("\n" + "=" * 70)
    print("CALCULATING CROSS-REPETITION POOLED METRICS AND CONSISTENCY")
    print("=" * 70)
    db = SessionLocal()
    try:
        group_detail = get_group_detail_service(db, GROUP_ID)
        comp = group_detail.get("comparison") or group_detail.get("across_repetition_summary") or {}
        b_m = comp.get("baseline_metrics", {})
        e_m = comp.get("egal_metrics", {})
        deltas = comp.get("deltas", {})

        print("\n--- POOLED METRICS SUMMARY (5 REPETITIONS) ---")
        metrics_to_show = [
            "task_completion_rate",
            "unsupported_action_rate",
            "recovery_rate",
            "consistency_rate",
            "false_success_rate",
        ]

        print(f"{'Metric':<25} | {'Baseline':<20} | {'EGAL':<20} | {'Delta':<15}")
        print("-" * 88)
        for mk in metrics_to_show:
            b_val = b_m.get(mk, {})
            e_val = e_m.get(mk, {})
            d_val = deltas.get(mk, {})
            b_str = f"{b_val.get('numerator')}/{b_val.get('denominator')} ({b_val.get('percentage')}%)" if b_val.get('percentage') is not None else "N/A"
            e_str = f"{e_val.get('numerator')}/{e_val.get('denominator')} ({e_val.get('percentage')}%)" if e_val.get('percentage') is not None else "N/A"
            d_str = f"{d_val.get('delta'):+.2f}% ({d_val.get('direction')})" if d_val.get('delta') is not None else "N/A"
            print(f"{mk:<25} | {b_str:<20} | {e_str:<20} | {d_str:<15}")

        # Dump summary to json file
        out_path = Path("scripts/postfix_experiment_results.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(group_detail, f, indent=2, default=str)
        print(f"\n[OUTPUT] Saved detailed group results to {out_path}")

    finally:
        db.close()


if __name__ == "__main__":
    main()
