"""
Automated continuous runner for Post-Fix V3 Experiment Suite.
Waits for Baseline Rep 1 to complete (currently running under task-3700),
then runs:
  - Baseline Repetitions 2, 3, 4, 5
  - EGAL Repetitions 1, 2, 3, 4, 5
  - Cross-repetition consistency aggregation
  - Group detail pooled metrics calculation
Saves final pooled summary to scratch/final_v3_results.json.
"""
import sys, os, time, json
from datetime import datetime
from pathlib import Path

# Ensure backend root is on sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app.database.session import SessionLocal
from app.models.entities import ExperimentRepetition, Evaluation
from app.services.consistency import aggregate_consistency
from app.services.grouping import get_group_detail_service
from scripts.run_postfix_v3_experiment import (
    execute_agent_repetition,
    GROUP_ID,
    REPETITION_COUNT,
)

SCRATCH_DIR = Path("scratch")
SCRATCH_DIR.mkdir(exist_ok=True)
OUT_PATH = SCRATCH_DIR / "final_v3_results.json"


def wait_for_baseline_rep1():
    print("[AUTO-RUNNER] Monitoring Baseline Repetition 1...", flush=True)
    while True:
        db = SessionLocal()
        try:
            rep = db.get(ExperimentRepetition, "rep_exp_postfix_baseline_003_1")
            status = rep.status if rep else "not_found"
            done = (rep.completed_run_count or 0) + (rep.failed_run_count or 0)
            tot = rep.run_count if rep else 18
            if rep and rep.status == "completed":
                print(f"[AUTO-RUNNER] Baseline Repetition 1 completed ({done}/{tot} runs)!", flush=True)
                break
            print(f"[AUTO-RUNNER] Baseline Rep 1 status: {status} ({done}/{tot} runs done). Waiting 15s...", flush=True)
        finally:
            db.close()
        time.sleep(15)


def run():
    print("=" * 70, flush=True)
    print("POST-FIX V3 AUTOMATED SUITE RUNNER", flush=True)
    print(f"Timestamp: {datetime.utcnow().isoformat()}", flush=True)
    print("=" * 70, flush=True)

    # 1. Wait for Baseline Rep 1 to finish
    wait_for_baseline_rep1()

    # 2. Baseline Repetitions 2 to 5
    for r in range(2, REPETITION_COUNT + 1):
        print(f"\n[AUTO-RUNNER] Starting Baseline Repetition {r}/{REPETITION_COUNT}...", flush=True)
        execute_agent_repetition("exp_postfix_baseline_003", r)

    # 3. EGAL Repetitions 1 to 5
    for r in range(1, REPETITION_COUNT + 1):
        print(f"\n[AUTO-RUNNER] Starting EGAL Repetition {r}/{REPETITION_COUNT}...", flush=True)
        execute_agent_repetition("exp_postfix_egal_003", r)

    # 4. Consistency Aggregation
    print("\n" + "=" * 70, flush=True)
    print("[AUTO-RUNNER] Running Consistency Aggregation...", flush=True)
    print("=" * 70, flush=True)

    db = SessionLocal()
    b_consistency = None
    e_consistency = None
    try:
        b_evals = (
            db.query(Evaluation)
            .filter_by(experiment_id="exp_postfix_baseline_003", status="completed")
            .order_by(Evaluation.repetition_index.asc())
            .all()
        )
        b_eids = [e.id for e in b_evals]
        if len(b_eids) >= 5:
            b_agg = aggregate_consistency(db, b_eids[:5], persist=True)
            b_consistency = {
                "rate": b_agg.consistency_rate,
                "consistent_groups": b_agg.consistent_group_count,
                "assessable_groups": b_agg.assessable_group_count,
                "evaluation_ids": b_eids[:5],
            }
            print(f"Baseline Consistency: {b_agg.consistency_rate}% ({b_agg.consistent_group_count}/{b_agg.assessable_group_count})", flush=True)

        e_evals = (
            db.query(Evaluation)
            .filter_by(experiment_id="exp_postfix_egal_003", status="completed")
            .order_by(Evaluation.repetition_index.asc())
            .all()
        )
        e_eids = [e.id for e in e_evals]
        if len(e_eids) >= 5:
            e_agg = aggregate_consistency(db, e_eids[:5], persist=True)
            e_consistency = {
                "rate": e_agg.consistency_rate,
                "consistent_groups": e_agg.consistent_group_count,
                "assessable_groups": e_agg.assessable_group_count,
                "evaluation_ids": e_eids[:5],
            }
            print(f"EGAL Consistency: {e_agg.consistency_rate}% ({e_agg.consistent_group_count}/{e_agg.assessable_group_count})", flush=True)

        # 5. Group Detail & Pooled Metrics
        print("\n" + "=" * 70, flush=True)
        print("[AUTO-RUNNER] Computing Group Pooled Metrics...", flush=True)
        print("=" * 70, flush=True)
        group_summary = get_group_detail_service(db, GROUP_ID)
        across = group_summary.get("across_repetitions_summary", {})

        output_data = {
            "group_id": GROUP_ID,
            "timestamp": datetime.utcnow().isoformat(),
            "baseline_consistency": b_consistency,
            "egal_consistency": e_consistency,
            "across_repetitions_summary": across,
        }

        with open(OUT_PATH, "w") as f:
            json.dump(output_data, f, indent=2, default=str)
        print(f"[AUTO-RUNNER] Successfully saved pooled results to {OUT_PATH}", flush=True)

    finally:
        db.close()


if __name__ == "__main__":
    run()
