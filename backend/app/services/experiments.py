import json, threading, uuid, time
from datetime import datetime, date
from pathlib import Path
from sqlalchemy.orm import Session
from app.models.entities import Experiment, DatasetSnapshot, Run, ExperimentRepetition
from app.integrations.registry import resolve_agent, providers
from app.services.datasets import _records
from app.core.config import settings

def _json_safe_key(key):
    if isinstance(key, (datetime, date)):
        return key.isoformat()
    if isinstance(key, str):
        return key
    if isinstance(key, (int, float, bool)):
        return str(key)
    raise TypeError(f"Key of type {type(key).__name__} is not JSON serializable")

def to_json_safe(value):
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, dict):
        return {_json_safe_key(k): to_json_safe(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_json_safe(v) for v in value]
    if isinstance(value, set):
        try:
            sorted_items = sorted(value)
        except TypeError:
            sorted_items = sorted(value, key=str)
        return [to_json_safe(v) for v in sorted_items]
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

def create_runs(db: Session, exp: Experiment, repetition_id: str | None = None, repetition_index: int = 1):
    snapshot = db.get(DatasetSnapshot, exp.dataset_snapshot_id)
    fmt = Path(snapshot.storage_path).suffix.lstrip(".")
    # JSONL locations are one-based line numbers while JSON array locations are
    # zero-based. Persist the same normalized index used by run_experiment.
    runs = [
        Run(
            id=f"run_{uuid.uuid4().hex}",
            experiment_id=exp.id,
            repetition_id=repetition_id,
            repetition_index=repetition_index,
            record_index=(i - 1 if fmt == "jsonl" else i),
            status="queued",
        )
        for i, _ in _records(Path(snapshot.storage_path), fmt)
    ]
    db.add_all(runs)
    db.commit()
    return runs

def run_experiment(db_factory, experiment_id: str, repetition_id: str | None = None):
    db = db_factory()
    try:
        exp = db.get(Experiment, experiment_id)
        if not exp:
            return
        exp.status = "running"
        rep = None
        if repetition_id:
            rep = db.get(ExperimentRepetition, repetition_id)
        else:
            rep = (
                db.query(ExperimentRepetition)
                .filter_by(experiment_id=experiment_id)
                .filter(ExperimentRepetition.status.in_(["starting", "queued", "running"]))
                .order_by(ExperimentRepetition.repetition_index.desc())
                .first()
            )
        if rep:
            rep.status = "running"
            rep.started_at = rep.started_at or datetime.utcnow()
        db.commit()

        run_query = db.query(Run).filter_by(experiment_id=experiment_id, status="queued")
        if rep:
            run_query = run_query.filter_by(repetition_id=rep.id)

        runs_to_process = run_query.order_by(Run.record_index).all()
        for run in runs_to_process:
            db.refresh(exp)
            if rep:
                db.refresh(rep)
            if exp.status in {"paused", "stopped"} or (rep and rep.status in {"paused", "stopped"}):
                break
            run.status = "running"
            run.started_at = datetime.utcnow()
            db.commit()
            try:
                snap = db.get(DatasetSnapshot, exp.dataset_snapshot_id)
                fmt = Path(snap.storage_path).suffix.lstrip(".")
                record = next(r for i, r in _records(Path(snap.storage_path), fmt) if (i - 1 if fmt == "jsonl" else i) == run.record_index)
                # The financial-news contract deliberately admits only the envelope's input object.
                # Ground truth and metadata remain evaluator/provenance data, never model input.
                payload = record.get("input") if exp.agent_id in {"financial_news_analysis", "financial_news_analysis_egal"} else {target: record[source] for source, target in exp.input_mapping.items() if source in record}
                agent = resolve_agent(db, exp.agent_id)
                if not agent:
                    raise ValueError("agent is unavailable or disabled")
                errs = agent.validate_configuration(exp.agent_configuration_snapshot or {}) + agent.validate_input(payload)
                if errs:
                    raise ValueError("; ".join(errs))
                configuration = {**(exp.agent_configuration_snapshot or {}), "provider_id": exp.provider_id}
                if getattr(exp, "model", None):
                    configuration["model_override"] = exp.model
                    configuration["model"] = exp.model

                # Check for failure_injection schedule in scenario metadata
                meta = record.get("metadata", {})
                orig = meta.get("original_record", {}) if isinstance(meta, dict) else {}
                failure_injection = orig.get("failure_injection") or (meta.get("failure_injection") if isinstance(meta, dict) else None) or record.get("failure_injection")
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
                            result = agent.run(current_payload, providers.get(exp.provider_id), configuration)
                            attempt_history.append({
                                "attempt": att_num,
                                "outcome": "success" if result.run_status == "completed" else "fail",
                                "error_code": result.error_code if result.run_status != "completed" else None,
                                "message": result.error_message if result.run_status != "completed" else "Execution succeeded on retry",
                                "execution_duration_ms": result.execution_duration_ms,
                                "timestamp": datetime.utcnow().isoformat(),
                            })
                            if result.run_status == "completed":
                                final_result = result
                                break

                    if final_result and final_result.run_status == "completed":
                        run.status = "completed"
                        raw_dict = (
                            dict(final_result.raw_output)
                            if isinstance(final_result.raw_output, dict)
                            else {"raw": final_result.raw_output}
                        )
                        raw_dict["_attempt_history"] = attempt_history
                        raw_dict["_retries_used"] = len([a for a in attempt_history if a.get("outcome") == "fail"])
                        raw_dict["_recovery_simulated"] = True
                        run.raw_output = raw_dict

                        norm_dict = (
                            dict(final_result.normalized_output)
                            if isinstance(final_result.normalized_output, dict)
                            else {}
                        )
                        norm_dict["_attempt_history"] = attempt_history
                        norm_dict["_retries_used"] = len([a for a in attempt_history if a.get("outcome") == "fail"])
                        run.normalized_output = norm_dict
                        run.output = norm_dict
                        run.execution_duration_ms = sum(a.get("execution_duration_ms", 0) for a in attempt_history) or final_result.execution_duration_ms
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
                        run.execution_duration_ms = sum(a.get("execution_duration_ms", 0) for a in attempt_history)
                else:
                    result = agent.run(payload, providers.get(exp.provider_id), configuration)
                    attempt_history = [{
                        "attempt": 1,
                        "outcome": "success" if result.run_status == "completed" else "fail",
                        "error_code": result.error_code if result.run_status != "completed" else None,
                        "message": result.error_message if result.run_status != "completed" else "Completed on initial attempt",
                        "execution_duration_ms": result.execution_duration_ms,
                        "timestamp": datetime.utcnow().isoformat(),
                    }]
                    run.execution_duration_ms = result.execution_duration_ms
                    if result.run_status == "completed":
                        run.status = "completed"
                        raw_dict = (
                            dict(result.raw_output)
                            if isinstance(result.raw_output, dict)
                            else {"raw": result.raw_output}
                        )
                        raw_dict["_attempt_history"] = attempt_history
                        raw_dict["_retries_used"] = 0
                        run.raw_output = raw_dict

                        norm_dict = (
                            dict(result.normalized_output)
                            if isinstance(result.normalized_output, dict)
                            else {}
                        )
                        norm_dict["_attempt_history"] = attempt_history
                        norm_dict["_retries_used"] = 0
                        run.normalized_output = norm_dict
                        run.output = norm_dict
                    else:
                        run.status = "failed"
                        run.error = {
                            "code": result.error_code or "RUN_FAILED",
                            "message": result.error_message or "Agent execution failed",
                            "attempt_history": attempt_history,
                            "retries_used": 0,
                        }
                        run.raw_output = {"_attempt_history": attempt_history, "_retries_used": 0}
                        run.normalized_output = None
                        run.output = None
            except Exception as exc:
                run.status = "failed"
                run.error = {"code": "RUN_FAILED", "message": str(exc)}
            run.completed_at = datetime.utcnow()
            if rep:
                if run.status == "completed":
                    rep.completed_run_count = (rep.completed_run_count or 0) + 1
                else:
                    rep.failed_run_count = (rep.failed_run_count or 0) + 1
            db.commit()

        db.refresh(exp)
        if rep:
            db.refresh(rep)
            rep.completed_at = datetime.utcnow()
            total_processed = (rep.completed_run_count or 0) + (rep.failed_run_count or 0)
            if rep.failed_run_count and rep.failed_run_count == total_processed and total_processed > 0:
                rep.status = "failed"
            else:
                rep.status = "completed"
            db.commit()
        if exp.status == "running":
            exp.status = "completed"
            db.commit()
    finally:
        db.close()

def start(db_factory, experiment_id: str, repetition_id: str | None = None):
    threading.Thread(target=run_experiment, args=(db_factory, experiment_id, repetition_id), daemon=True).start()

def create_repetition(
    db: Session,
    exp: Experiment,
    idempotency_key: str | None = None,
    db_factory = None,
) -> ExperimentRepetition:
    """Creates a new repetition reusing frozen experiment configuration and starts execution."""
    # 1. Idempotency check: if matching key exists for this experiment, return it
    if idempotency_key:
        existing_rep = (
            db.query(ExperimentRepetition)
            .filter_by(experiment_id=exp.id, idempotency_key=idempotency_key)
            .first()
        )
        if existing_rep:
            return existing_rep

    # 2. Debounce / duplicate start check:
    active_rep = (
        db.query(ExperimentRepetition)
        .filter_by(experiment_id=exp.id)
        .filter(ExperimentRepetition.status.in_(["starting", "running"]))
        .order_by(ExperimentRepetition.repetition_index.desc())
        .first()
    )
    if active_rep:
        time_diff = (datetime.utcnow() - active_rep.created_at).total_seconds()
        if time_diff < 3.0:
            return active_rep
        raise ValueError("Cannot start a new repetition while experiment execution is actively running.")

    # 3. Determine next repetition index
    existing_reps = db.query(ExperimentRepetition).filter_by(experiment_id=exp.id).all()
    if existing_reps:
        next_index = max(r.repetition_index for r in existing_reps) + 1
    else:
        existing_runs = db.query(Run).filter_by(experiment_id=exp.id).all()
        if existing_runs:
            next_index = max((r.repetition_index or 1) for r in existing_runs) + 1
        else:
            next_index = 1

    # 4. Create new repetition
    rep_id = f"rep_{uuid.uuid4().hex}"
    rep = ExperimentRepetition(
        id=rep_id,
        experiment_id=exp.id,
        repetition_index=next_index,
        status="starting",
        idempotency_key=idempotency_key,
        created_at=datetime.utcnow(),
        started_at=datetime.utcnow(),
    )
    db.add(rep)
    db.flush()

    # 5. Create runs for this repetition
    new_runs = create_runs(db, exp, repetition_id=rep.id, repetition_index=next_index)
    rep.run_count = len(new_runs)
    exp.status = "starting"
    db.commit()
    db.refresh(rep)

    # 6. Start asynchronous execution
    if db_factory:
        start(db_factory, exp.id, repetition_id=rep.id)
    return rep
