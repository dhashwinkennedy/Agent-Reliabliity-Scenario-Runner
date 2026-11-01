import sys, os
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
import json
from app.database.session import SessionLocal
from app.models.entities import RunEvaluation, Evaluation, Run

db = SessionLocal()

REPEATABILITY_IDS = [
    "NORMAL-001",
    "NORMAL-004",
    "AMBIGUOUS-001",
    "AMBIGUOUS-005",
    "FAILURE-001",
    "FAILURE-003",
]

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

results = {}

for exp_id in ["exp_postfix_baseline_002", "exp_postfix_egal_002"]:
    agent_name = "Baseline" if "baseline" in exp_id else "EGAL"
    print("=" * 70)
    print(f"EXPERIMENT: {exp_id} ({agent_name})")
    print("=" * 70)
    evals = db.query(Evaluation).filter_by(experiment_id=exp_id).order_by(Evaluation.repetition_index.asc()).all()
    print(f"Total evaluations: {len(evals)}")
    
    results[agent_name] = {}
    
    for sc_id in REPEATABILITY_IDS:
        print(f"\n--- SCENARIO: {sc_id} ---")
        rep_data = []
        for ev in evals:
            rev = db.query(RunEvaluation).filter_by(evaluation_id=ev.id, scenario_id=sc_id).first()
            if not rev:
                rep_data.append({"rep": ev.repetition_index, "run_id": None, "error": "MISSING"})
                continue
            sig = rev.decision_signature or {}
            dim_vals = {
                "rep": ev.repetition_index,
                "run_id": rev.run_id,
                "execution_status": rev.execution_status,
                "task_completion_status": (rev.task_completion or {}).get("status"),
                "unsupported_action_present": (rev.unsupported_action or {}).get("present"),
                "recovery_status": (rev.recovery or {}).get("status"),
                "sentiment": sig.get("sentiment"),
                "price_impact": sig.get("price_impact"),
                "recommendation": sig.get("recommendation"),
                "forecast_present": sig.get("forecast_present"),
                "forecast_horizon": sig.get("forecast_horizon"),
            }
            rep_data.append(dim_vals)
            
        results[agent_name][sc_id] = rep_data
        
        # Print table
        for d in rep_data:
            print(f"  Rep {d['rep']} ({d['run_id']}): exec={d.get('execution_status')}, tc={d.get('task_completion_status')}, ua={d.get('unsupported_action_present')}, rec={d.get('recovery_status')}, sent={d.get('sentiment')}, pi={d.get('price_impact')}, recmd={d.get('recommendation')}, fc_p={d.get('forecast_present')}, fc_h={d.get('forecast_horizon')}")
        
        # Check differences
        differing = []
        for dim in COMPARED_DIMENSIONS:
            vals = [d.get(dim) for d in rep_data]
            # Normalize for hashable comparison
            distinct = []
            for v in vals:
                if v not in distinct:
                    distinct.append(v)
            if len(distinct) > 1:
                differing.append((dim, vals))
                
        if differing:
            print(f"  >> INCONSISTENT. Differing dimensions ({len(differing)}):")
            for dim, vals in differing:
                print(f"     - {dim}: {vals}")
        else:
            print(f"  >> CONSISTENT across all 9 dimensions!")

with open("scripts/consistency_detailed_matrix.json", "w", encoding="utf-8") as f:
    json.dump(results, f, indent=2)

db.close()
