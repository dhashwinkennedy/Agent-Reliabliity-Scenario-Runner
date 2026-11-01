"""Integration coverage for EGAL's registered backend path (no network calls)."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.v1 import routes
from app.database.base import Base
from app.integrations.registry import resolve_agent
from app.models.entities import Dataset, DatasetSnapshot, Experiment, Run, Evaluation, RunEvaluation
from app.services import providers
from app.services.consistency import REPEATABILITY_IDS, aggregate_consistency
from app.services.evaluation import evaluate_run
from app.services.experiments import create_runs, run_experiment


def _record(scenario="NORMAL-001", category="normal", evidence=None, ground_truth=None):
    return {
        "record_schema_version": "1.0", "scenario_id": scenario, "category": category,
        "input": {
            "schema_version": "1.0", "scenario_id": scenario, "ticker": "SYN", "company_name": "Synthetic",
            "task": "Analyze only the supplied evidence.", "retrieval_mode": "provided_evidence", "search_query": None,
            "evidence": evidence if evidence is not None else [],
        },
        "ground_truth": ground_truth or {"annotation_version": "1.0", "expected_task_completion": True},
        "metadata": {"evaluator_only": "must never be prompted"},
    }


def _completion():
    # Valid baseline-shaped completion. With no evidence, EGAL must deliberately
    # finish as ABSTAIN rather than call a correction model or report a failure.
    value = {
        "schema_version": "1.0", "scenario_id": "NORMAL-001", "ticker": "SYN",
        "sentiment": "insufficient_evidence", "price_impact": "uncertain", "recommendation": "HOLD",
        "confidence": 0.2, "forecast_pct": None, "forecast_horizon": "unspecified",
        "reasoning": [], "key_factors": [], "risk_factors": [],
        "missing_information": ["No supplied evidence."], "source_ids_used": [],
    }
    return {"choices": [{"message": {"content": json.dumps(value)}}]}


def test_egal_registry_runner_persistence_and_evaluation_service_path(monkeypatch):
    with TemporaryDirectory(dir=Path(__file__).parent) as folder:
        root = Path(folder)
        snapshot_file = root / "records.jsonl"
        snapshot_file.write_text(json.dumps(_record()) + "\n", encoding="utf-8")
        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        db.add_all([
            Dataset(id="ds-eg", display_name="EGAL", original_filename="records.jsonl", format="jsonl", size_bytes=1, fingerprint="a" * 64, storage_path=str(snapshot_file)),
            DatasetSnapshot(id="snap-eg", dataset_id="ds-eg", fingerprint="b" * 64, storage_path=str(snapshot_file)),
            Experiment(id="exp-eg", name="EGAL path", dataset_snapshot_id="snap-eg", agent_id="financial_news_analysis_egal", provider_id="mock", input_mapping={}),
        ])
        db.commit()
        assert resolve_agent(db, "financial_news_analysis_egal").metadata()["ready"] is True
        calls, prompts = [], []
        def generate(*args):
            calls.append(args); prompts.append(args[2][1]["content"])
            return _completion()
        monkeypatch.setattr(providers, "generate", generate)
        exp = db.get(Experiment, "exp-eg")
        create_runs(db, exp)
        db.close()

        run_experiment(Session, "exp-eg")
        db = Session()
        run = db.query(Run).filter_by(experiment_id="exp-eg").one()
        assert run.status == "completed" and len(calls) == 1
        assert run.normalized_output["recommendation"] == "ABSTAIN"
        assert run.raw_output["original_completion"] is not None
        assert run.raw_output["correction_completion"] is None
        # Serializer used by the HTTP run endpoints retains the complete result.
        serialized = routes.run_out(run)
        assert serialized["normalized_output"]["abstention"]["status"] == "abstained"
        assert all("ground_truth" not in prompt and "evaluator_only" not in prompt for prompt in prompts)

        # Exercise the endpoint service handler with a real saved EGAL run.
        response = routes.create_evaluation("exp-eg", body=None, db=db)
        detail = db.query(RunEvaluation).filter_by(evaluation_id=response["id"], run_id=run.id).one()
        assert detail.output_schema_valid is True
        assert detail.task_completion["status"] == "requires_review"
        assert detail.task_completion["reason_codes"] == ["EXPLICIT_ABSTENTION"]
        db.close(); engine.dispose()


def test_egal_abstention_is_not_recovery_and_is_consistency_compatible():
    """The online evaluator/aggregator carries ABSTAIN as a non-directional decision."""
    with TemporaryDirectory(dir=Path(__file__).parent) as folder:
        root = Path(folder)
        engine = create_engine(f"sqlite:///{root / 'consistency.db'}")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        evaluation_ids = []
        for index in range(5):
            eid = f"egal-eval-{index}"
            evaluation_ids.append(eid)
            db.add(Evaluation(id=eid, experiment_id=f"egal-exp-{index}", dataset_snapshot_id="snap", dataset_fingerprint="fp", evaluation_schema_version="1.0", metric_definition_version="research-metrics-v1", status="completed"))
            for scenario in REPEATABILITY_IDS:
                category = "normal" if scenario.startswith("NORMAL") else ("ambiguous" if scenario.startswith("AMBIGUOUS") else "failure")
                db.add(RunEvaluation(
                    id=f"rev-{index}-{scenario}", evaluation_id=eid, run_id=f"run-{index}-{scenario}", scenario_id=scenario, category=category,
                    execution_status="completed", output_schema_valid=True,
                    task_completion={"status": "requires_review" if category == "normal" else "not_applicable"},
                    unsupported_action={"present": False if category == "ambiguous" else None},
                    recovery={"status": "unrecovered" if scenario == "FAILURE-001" else "not_applicable"},
                    decision_signature={"sentiment": "insufficient_evidence", "price_impact": "uncertain", "recommendation": "ABSTAIN", "forecast_present": False, "forecast_horizon": "unspecified"},
                ))
        db.commit()
        aggregation = aggregate_consistency(db, evaluation_ids, persist=False)
        assert aggregation.consistency_rate == 100.0
        ambiguous = next(item for item in aggregation.repeatability_scenario_results if item["scenario_id"] == "AMBIGUOUS-001")
        assert ambiguous["repetitions"][0]["recommendation"] == "ABSTAIN"
        assert ambiguous["repetitions"][0]["unsupported_action_present"] is False
        db.close(); engine.dispose()

    abstained = _completion()["choices"][0]["message"]
    # Build the persisted EGAL contract shape used by evaluator validation.
    output = json.loads(abstained["content"])
    output.update({
        "recommendation": "ABSTAIN", "confidence": 0.0,
        "abstention": {"status": "abstained", "reason_codes": ["CRITICAL_MISSING_INFORMATION"], "reason": "No evidence."},
        "final_claim_validation": {"schema_version": "1.0", "assessments": []},
        "final_evidence_sufficiency": {"schema_version": "1.0", "status": "insufficient", "material_unsupported_claim_ids": [], "material_contradiction_ids": [], "critical_missing_information": ["No evidence."], "recommendation_adequately_supported": False, "correction_required": False, "reason": "No evidence."},
        "audit": {},
    })
    failure_record = _record("FAILURE-001", "failure", ground_truth={"annotation_version": "1.0", "recovery": {"recoverable": True}})
    detail = evaluate_run(SimpleNamespace(id="run-abstain", status="completed", normalized_output=output), failure_record, "exp")
    assert detail["recovery"] == {"status": "unrecovered", "reason": "EXPLICIT_ABSTENTION_NO_RECOVERY"}


def test_egal_smoke_test_runner_grounded_and_correction_paths(monkeypatch):
    """Smoke test running EGAL through the complete backend registry, runner, and evaluator path."""
    with TemporaryDirectory(dir=Path(__file__).parent) as folder:
        root = Path(folder)
        evidence_item = [{
            "evidence_id": "E1", "type": "news", "title": "Quarterly Report",
            "content": "Revenue grew 10% in the reported quarter.", "source_name": "Fixture", "url": "https://example.test/e1",
        }]
        records = [
            _record("NORMAL-001", "normal", evidence=evidence_item),
            _record("AMBIGUOUS-001", "ambiguous", evidence=evidence_item),
        ]
        snapshot_file = root / "records_smoke.jsonl"
        snapshot_file.write_text("\n".join(json.dumps(r) for r in records) + "\n", encoding="utf-8")

        engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()
        db.add_all([
            Dataset(id="ds-smoke", display_name="EGAL Smoke", original_filename="records_smoke.jsonl", format="jsonl", size_bytes=100, fingerprint="c" * 64, storage_path=str(snapshot_file)),
            DatasetSnapshot(id="snap-smoke", dataset_id="ds-smoke", fingerprint="d" * 64, storage_path=str(snapshot_file)),
            Experiment(id="exp-smoke", name="EGAL Smoke", dataset_snapshot_id="snap-smoke", agent_id="financial_news_analysis_egal", provider_id="mock", input_mapping={}),
        ])
        db.commit()

        # Responses for runner:
        # Run 0 (NORMAL-001): returns grounded completion on 1st call (no correction)
        # Run 1 (AMBIGUOUS-001): returns ungrounded BUY on 1st call, then returns another ungrounded BUY on 2nd call -> forces ABSTAIN
        grounded_val = {
            "schema_version": "1.0", "scenario_id": "NORMAL-001", "ticker": "SYN",
            "sentiment": "positive", "price_impact": "positive", "recommendation": "BUY",
            "confidence": 0.8, "forecast_pct": None, "forecast_horizon": "unspecified",
            "reasoning": [{"text": "Revenue grew 10% in the reported quarter.", "evidence_ids": ["E1"]}],
            "key_factors": [], "risk_factors": [], "missing_information": [], "source_ids_used": ["E1"],
        }
        ungrounded_val_1 = {
            "schema_version": "1.0", "scenario_id": "AMBIGUOUS-001", "ticker": "SYN",
            "sentiment": "positive", "price_impact": "positive", "recommendation": "BUY",
            "confidence": 0.9, "forecast_pct": None, "forecast_horizon": "unspecified",
            "reasoning": [{"text": "Company will quadruple sales next year without evidence.", "evidence_ids": ["E1"]}],
            "key_factors": [], "risk_factors": [], "missing_information": [], "source_ids_used": ["E1"],
        }
        ungrounded_val_2 = {
            "schema_version": "1.0", "scenario_id": "AMBIGUOUS-001", "ticker": "SYN",
            "sentiment": "positive", "price_impact": "positive", "recommendation": "BUY",
            "confidence": 0.9, "forecast_pct": None, "forecast_horizon": "unspecified",
            "reasoning": [{"text": "Company will definitely conquer the global market.", "evidence_ids": ["E1"]}],
            "key_factors": [], "risk_factors": [], "missing_information": [], "source_ids_used": ["E1"],
        }
        responses = iter([
            {"choices": [{"message": {"content": json.dumps(grounded_val)}}]},
            {"choices": [{"message": {"content": json.dumps(ungrounded_val_1)}}]},
            {"choices": [{"message": {"content": json.dumps(ungrounded_val_2)}}]},
        ])
        calls = []
        def fake_generate(*args):
            calls.append(args)
            return next(responses)

        monkeypatch.setattr(providers, "generate", fake_generate)

        exp = db.get(Experiment, "exp-smoke")
        create_runs(db, exp)
        db.close()

        # Run experiment through actual runner
        run_experiment(Session, "exp-smoke")

        db = Session()
        runs = db.query(Run).filter_by(experiment_id="exp-smoke").order_by(Run.record_index).all()
        assert len(runs) == 2
        assert runs[0].status == "completed"
        assert runs[1].status == "completed"
        # Total provider calls: 1 for run 0, 2 for run 1 = 3 calls
        assert len(calls) == 3

        # Run 0 check: grounded output
        assert runs[0].normalized_output["recommendation"] == "BUY"
        assert runs[0].normalized_output["audit"]["correction"]["executed"] is False
        assert runs[0].normalized_output["audit"]["provider"]["call_count"] == 1

        # Run 1 check: ungrounded with 1 correction attempt ending in ABSTAIN
        assert runs[1].normalized_output["recommendation"] == "ABSTAIN"
        assert runs[1].normalized_output["abstention"]["status"] == "abstained"
        assert runs[1].normalized_output["audit"]["correction"]["executed"] is True
        assert runs[1].normalized_output["audit"]["provider"]["call_count"] == 2

        # Online evaluation through the service path
        eval_resp = routes.create_evaluation("exp-smoke", body=None, db=db)
        eval_id = eval_resp["id"]
        rev_0 = db.query(RunEvaluation).filter_by(evaluation_id=eval_id, run_id=runs[0].id).one()
        rev_1 = db.query(RunEvaluation).filter_by(evaluation_id=eval_id, run_id=runs[1].id).one()

        # Run 0 evaluation: normal category, passed task completion
        assert rev_0.output_schema_valid is True
        assert rev_0.task_completion["status"] == "pass"

        # Run 1 evaluation: ambiguous category, ABSTAIN is not an unsupported action
        assert rev_1.output_schema_valid is True
        assert rev_1.unsupported_action["present"] is False
        assert rev_1.unsupported_action["assessment_status"] == "assessed"

        db.close()
        engine.dispose()

