import json
from pathlib import Path
from tempfile import TemporaryDirectory
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database.base import Base
from app.models.entities import Dataset, DatasetSnapshot, Experiment, Run, Evaluation
from app.services.evaluation import evaluate_experiment, calculate_metrics, EVALUATION_SCHEMA_VERSION

def output(scenario, text, recommendation="HOLD"):
    return {"schema_version":"1.0","scenario_id":scenario,"ticker":"SYN","sentiment":"neutral","price_impact":"uncertain","recommendation":recommendation,"confidence":0.4,"forecast_pct":None,"forecast_horizon":"unspecified","reasoning":[{"text":text,"evidence_ids":["E1"]}],"key_factors":[],"risk_factors":[],"missing_information":["More evidence"],"source_ids_used":["E1"]}

def record(scenario, category, truth):
    return {"record_schema_version":"1.0","scenario_id":scenario,"category":category,"input":{"schema_version":"1.0","scenario_id":scenario,"ticker":"SYN","company_name":"Synthetic","task":"Analyze.","retrieval_mode":"provided_evidence","search_query":None,"evidence":[{"evidence_id":"E1","type":"news","title":"T","content":"C","source_name":"S","url":"https://example.test"}]},"ground_truth":truth,"metadata":{"source_mode":"test"}}

def test_evaluation_persists_annotation_driven_metrics():
    with TemporaryDirectory(dir=Path(__file__).parent) as folder:
        root=Path(folder); snapshot_path=root/"scenario.jsonl"
        rows=[record("NORMAL-001","normal",{"annotation_version":"1.0","expected_task_completion":True,"supported_facts":[{"text":"Supported fact","evidence_ids":["E1"]}]}),record("AMBIGUOUS-001","ambiguous",{"annotation_version":"1.0","unsupported_claims":[{"text":"Unsupported action","evidence_ids":["E1"]}]})]
        snapshot_path.write_text("\n".join(json.dumps(x) for x in rows)+"\n",encoding="utf-8")
        engine=create_engine(f"sqlite:///{root/'evaluation.db'}"); Base.metadata.create_all(engine); Session=sessionmaker(bind=engine); db=Session()
        dataset=Dataset(id="ds",display_name="d",original_filename="d.jsonl",format="jsonl",size_bytes=1,fingerprint="a"*64,storage_path=str(snapshot_path)); snap=DatasetSnapshot(id="snap",dataset_id="ds",fingerprint="b"*64,storage_path=str(snapshot_path)); exp=Experiment(id="exp",name="e",dataset_snapshot_id="snap",agent_id="financial_news_analysis",provider_id="mock",input_mapping={})
        db.add_all([dataset,snap,exp,Run(id="run-normal",experiment_id="exp",record_index=0,status="completed",normalized_output=output("NORMAL-001","Supported fact")),Run(id="run-ambiguous",experiment_id="exp",record_index=1,status="completed",normalized_output=output("AMBIGUOUS-001","Unsupported action","BUY"))]); db.commit()
        first=evaluate_experiment(db,exp); second=evaluate_experiment(db,exp)
        assert first.id == second.id and db.query(Evaluation).count() == 1
        assert first.metrics["task_completion_rate"]["numerator"] == 1
        assert first.metrics["task_completion_rate"]["denominator"] == 1
        assert first.metrics["unsupported_action_rate"]["numerator"] == 1
        assert first.metrics["unsupported_action_rate"]["denominator"] == 1
        assert first.metrics["recovery_rate"]["percentage"] is None
        db.close(); engine.dispose()

def test_invalid_output_does_not_pass_and_consistency_is_incomplete():
    class Result:
        def __init__(self,scenario,status="requires_review",valid=True):
            self.scenario_id=scenario; self.category="normal"; self.task_completion={"status":status}; self.unsupported_action={"assessment_status":"unscored","present":None,"count":0}; self.recovery={"status":"not_applicable"}; self.execution_status="completed"; self.output_schema_valid=valid; self.claim_assessments=[]
    results=[Result("NORMAL-001","fail",False)]
    metrics=calculate_metrics(results,[("NORMAL-001","normal")])
    assert metrics["task_completion_rate"]["numerator"] == 0 and metrics["task_completion_rate"]["denominator"] == 1
    assert metrics["consistency_rate"]["status"] == "partial"

def test_consistency_uses_material_decisions_not_wording():
    class Result:
        category="normal"; task_completion={"status":"pass"}; unsupported_action={"assessment_status":"assessed","present":False,"count":0}; recovery={"status":"not_applicable"}; execution_status="completed"; output_schema_valid=True; claim_assessments=[]
        def __init__(self,recommendation): self.scenario_id="NORMAL-001"; self.decision_signature={"sentiment":"positive","price_impact":"positive","recommendation":recommendation,"forecast_present":False,"forecast_horizon":"unspecified"}
    same=calculate_metrics([Result("BUY") for _ in range(5)],[("NORMAL-001","normal")])
    changed=calculate_metrics([Result("BUY") for _ in range(4)]+[Result("HOLD")],[("NORMAL-001","normal")])
    assert same["consistency_rate"]["numerator"] == 1 and same["consistency_rate"]["denominator"] == 1
    assert changed["consistency_rate"]["numerator"] == 0 and changed["consistency_rate"]["denominator"] == 1

def test_evaluation_readiness_lifecycle_rules():
    from app.services.evaluation import check_evaluation_readiness
    with TemporaryDirectory(dir=Path(__file__).parent) as folder:
        root = Path(folder)
        snapshot_path = root / "scenario.jsonl"
        rows = [
            record("NORMAL-001", "normal", {"annotation_version": "1.0", "expected_task_completion": True}),
            record("NORMAL-002", "normal", {"annotation_version": "1.0", "expected_task_completion": True}),
        ]
        snapshot_path.write_text("\n".join(json.dumps(x) for x in rows) + "\n", encoding="utf-8")
        engine = create_engine(f"sqlite:///{root/'readiness.db'}")
        Base.metadata.create_all(engine)
        Session = sessionmaker(bind=engine)
        db = Session()

        dataset = Dataset(id="ds-ready", display_name="d", original_filename="d.jsonl", format="jsonl", size_bytes=1, fingerprint="a"*64, storage_path=str(snapshot_path))
        snap = DatasetSnapshot(id="snap-ready", dataset_id="ds-ready", fingerprint="b"*64, storage_path=str(snapshot_path))
        db.add_all([dataset, snap])
        db.commit()

        # Test 1: Completed experiment + terminal runs -> evaluation allowed
        exp_completed = Experiment(id="exp-completed", name="e1", dataset_snapshot_id="snap-ready", agent_id="mock", provider_id="mock", status="completed")
        db.add(exp_completed)
        db.add(Run(id="run-c1", experiment_id="exp-completed", record_index=0, status="completed", normalized_output=output("NORMAL-001", "T")))
        db.commit()
        ready, code, msg = check_evaluation_readiness(db, exp_completed)
        assert ready is True

        # Test 2: Stopped/incomplete experiment + terminal saved runs -> evaluation allowed
        exp_stopped = Experiment(id="exp-stopped", name="e2", dataset_snapshot_id="snap-ready", agent_id="mock", provider_id="mock", status="stopped")
        db.add(exp_stopped)
        db.add(Run(id="run-s1", experiment_id="exp-stopped", record_index=0, status="completed", normalized_output=output("NORMAL-001", "T")))
        db.commit()
        ready, code, msg = check_evaluation_readiness(db, exp_stopped)
        assert ready is True
        eval_stopped = evaluate_experiment(db, exp_stopped, force=True)
        assert eval_stopped.manifest["evaluation_status"] == "INCOMPLETE"
        assert eval_stopped.manifest["completed_run_count"] == 1
        assert eval_stopped.manifest["expected_run_count"] == 2

        # Test 3: Experiment with active RUNNING run -> rejected
        exp_running = Experiment(id="exp-running", name="e3", dataset_snapshot_id="snap-ready", agent_id="mock", provider_id="mock", status="running")
        db.add(exp_running)
        db.add(Run(id="run-r1", experiment_id="exp-running", record_index=0, status="running"))
        db.commit()
        ready, code, msg = check_evaluation_readiness(db, exp_running)
        assert ready is False
        assert code == "EXPERIMENT_STILL_ACTIVE"

        # Test 4: Experiment with active QUEUED run -> rejected
        exp_queued = Experiment(id="exp-queued", name="e4", dataset_snapshot_id="snap-ready", agent_id="mock", provider_id="mock", status="stopped")
        db.add(exp_queued)
        db.add(Run(id="run-q1", experiment_id="exp-queued", record_index=0, status="queued"))
        db.commit()
        ready, code, msg = check_evaluation_readiness(db, exp_queued)
        assert ready is False
        assert code == "EXPERIMENT_STILL_ACTIVE"

        # Test 5: Experiment with failed terminal runs -> evaluation allowed, reported
        exp_failed_run = Experiment(id="exp-failed-run", name="e5", dataset_snapshot_id="snap-ready", agent_id="mock", provider_id="mock", status="completed")
        db.add(exp_failed_run)
        db.add(Run(id="run-f1", experiment_id="exp-failed-run", record_index=0, status="failed", error={"code": "TIMEOUT"}))
        db.commit()
        ready, code, msg = check_evaluation_readiness(db, exp_failed_run)
        assert ready is True
        eval_failed = evaluate_experiment(db, exp_failed_run, force=True)
        assert eval_failed.manifest["failed_run_count"] == 1

        # Test 6: Experiment with no saved runs -> rejected
        exp_empty = Experiment(id="exp-empty", name="e6", dataset_snapshot_id="snap-ready", agent_id="mock", provider_id="mock", status="draft")
        db.add(exp_empty)
        db.commit()
        ready, code, msg = check_evaluation_readiness(db, exp_empty)
        assert ready is False
        assert code == "NO_SAVED_RUNS"

        # Test 7: Evaluation already running -> duplicate rejected
        active_eval = Evaluation(
            id="eval-active",
            experiment_id="exp-completed",
            dataset_snapshot_id="snap-ready",
            dataset_fingerprint="b"*64,
            evaluation_schema_version="1.0",
            metric_definition_version="v1",
            status="running"
        )
        db.add(active_eval)
        db.commit()
        ready, code, msg = check_evaluation_readiness(db, exp_completed)
        assert ready is False
        assert code == "EVALUATION_ALREADY_RUNNING"

        db.close()
        engine.dispose()

def test_regression_tests_a_through_e_fact_assessments():
    from app.services.evaluation import assess_fact_status

    fact_310 = "Contract value is ₹310 crore."
    contra_3100 = ["The contract is valued at ₹3,100 crore."]

    # Test A: correct value
    agent_a = ["The contract is valued at ₹310 crore and services begin on 1 January."]
    status_a = assess_fact_status(fact_310, agent_a, contra_3100)
    assert status_a == "SUPPORTED"

    # Test B: contradictory value
    agent_b = ["The contract is valued at ₹3,100 crore."]
    status_b = assess_fact_status(fact_310, agent_b, contra_3100)
    assert status_b == "CONTRADICTED"

    # Test C: missing value
    agent_c = ["SecureNet signed a three-year agreement with Meridian Bank."]
    status_c = assess_fact_status(fact_310, agent_c, contra_3100)
    assert status_c == "MISSING"

    # Test D: equivalent formatting (INR 310 crore and Rs. 310 crore)
    agent_d1 = ["The contract value is INR 310 crore."]
    status_d1 = assess_fact_status(fact_310, agent_d1, contra_3100)
    assert status_d1 == "SUPPORTED"

    agent_d2 = ["Value of contract: Rs. 310 crore."]
    status_d2 = assess_fact_status(fact_310, agent_d2, contra_3100)
    assert status_d2 == "SUPPORTED"

    # Test E: branch coverage omitted -> MISSING, not contradiction
    fact_branches = "Managed cybersecurity services across 2,200 branches of Meridian Bank."
    agent_e = ["SecureNet signed a three-year agreement with Meridian Bank to provide managed cybersecurity services."]
    status_e = assess_fact_status(fact_branches, agent_e, contra_3100)
    assert status_e == "MISSING"

def test_normal_006_end_to_end_evaluation_passes():
    from app.models.entities import Run
    from app.services.evaluation import evaluate_run

    gt_normal_006 = {
        "annotation_version": "1.0",
        "expected_task_completion": True,
        "supported_facts": [
            {"text": "Three-year agreement for managed cybersecurity services across 2,200 branches of Meridian Bank.", "evidence_ids": ["E1"]},
            {"text": "Contract value is ₹310 crore.", "evidence_ids": ["E1"]},
            {"text": "Services begin on 1 January.", "evidence_ids": ["E1"]},
            {"text": "SecureNet said revenue will be recognised evenly over the contract term.", "evidence_ids": ["E1"]},
            {"text": "SecureNet described it as its largest single banking contract (company characterisation).", "evidence_ids": ["E1"]},
            {"text": "Meridian Bank did not comment on the terms.", "evidence_ids": ["E1"]},
        ],
        "contradictions": [
            {"text": "The contract is valued at ₹3,100 crore.", "evidence_ids": []},
            {"text": "The agreement runs five years.", "evidence_ids": []},
            {"text": "Services begin in July.", "evidence_ids": []},
            {"text": "Meridian Bank endorsed the terms.", "evidence_ids": []},
        ],
        "unsupported_claims": [
            {"text": "The contract has a 25% margin.", "evidence_ids": []},
            {"text": "Meridian will renew after three years.", "evidence_ids": []},
        ],
        "missing_information": [
            "Contract margin, renewal terms and exclusivity are not disclosed."
        ],
    }

    record_normal_006 = {
        "scenario_id": "NORMAL-006",
        "category": "normal",
        "input": {
            "evidence": [{
                "evidence_id": "E1",
                "content": "SecureNet signed a three-year agreement with Meridian Bank to provide managed cybersecurity services across the bank's 2,200 branches. The contract is valued at ₹310 crore and services begin on 1 January. SecureNet said it would recognise revenue evenly over the contract term and described the agreement as its largest single banking contract. Meridian Bank did not comment on the terms."
            }]
        },
        "ground_truth": gt_normal_006,
    }

    # 1. Baseline agent output
    baseline_output = {
        "schema_version": "1.0",
        "scenario_id": "NORMAL-006",
        "ticker": "SCNT.SYN",
        "sentiment": "neutral",
        "price_impact": "neutral",
        "recommendation": "HOLD",
        "confidence": 0.7,
        "forecast_pct": None,
        "forecast_horizon": "short_term",
        "reasoning": [
            {"text": "SecureNet signed a three-year agreement with Meridian Bank to provide managed cybersecurity services.", "evidence_ids": ["E1"]},
            {"text": "The contract is valued at ₹310 crore and services begin on 1 January.", "evidence_ids": ["E1"]},
            {"text": "SecureNet said it would recognise revenue evenly over the contract term and described the agreement as its largest single banking contract.", "evidence_ids": ["E1"]},
        ],
        "key_factors": [
            {"text": "Revenue recognition policy of recognizing revenue evenly over the contract term.", "evidence_ids": ["E1"]}
        ],
        "risk_factors": [
            {"text": "The absence of a confirmation from Meridian Bank regarding the terms of the contract.", "evidence_ids": ["E1"]}
        ],
        "missing_information": [
            "Specifics of the services provided under the contract."
        ],
        "source_ids_used": ["E1"],
    }
    run_baseline = Run(id="run-base-6", experiment_id="exp-1", record_index=5, status="completed", normalized_output=baseline_output)
    eval_baseline = evaluate_run(run_baseline, record_normal_006, "exp-1")
    assert eval_baseline["task_completion"]["status"] == "pass"
    assert eval_baseline["false_success"]["status"] == "pass"
    # Verify no claim is marked contradiction
    assert not any(c["assessment_status"] == "contradiction" for c in eval_baseline["claim_assessments"])

    # 2. EGAL agent output
    egal_output = {
        "schema_version": "1.0",
        "scenario_id": "NORMAL-006",
        "ticker": "SCNT.SYN",
        "sentiment": "neutral",
        "price_impact": "neutral",
        "recommendation": "HOLD",
        "confidence": 0.75,
        "forecast_pct": None,
        "forecast_horizon": "short_term",
        "reasoning": [
            {"text": "SecureNet signed a three-year agreement with Meridian Bank, expanding its managed cybersecurity services.", "evidence_ids": ["E1"]}
        ],
        "key_factors": [
            {"text": "Value of the contract is ₹310 crore.", "evidence_ids": ["E1"]},
            {"text": "Revenue recognition will be spread evenly over three years.", "evidence_ids": ["E1"]},
        ],
        "risk_factors": [
            {"text": "Meridian Bank did not comment on the terms, which may indicate concerns or ambiguity regarding the agreement.", "evidence_ids": ["E1"]}
        ],
        "missing_information": [
            "Specific financial terms and details on service scope that might have influenced the agreement"
        ],
        "source_ids_used": ["E1"],
        "abstention": {"status": "not_abstained", "reason_codes": [], "reason": "A defensible recommendation remains."},
    }
    run_egal = Run(id="run-egal-6", experiment_id="exp-2", record_index=5, status="completed", normalized_output=egal_output)
    eval_egal = evaluate_run(run_egal, record_normal_006, "exp-2")
    assert eval_egal["task_completion"]["status"] == "pass"
    assert eval_egal["false_success"]["status"] == "pass"
    assert not any(c["assessment_status"] == "contradiction" for c in eval_egal["claim_assessments"])

def test_normal_002_missing_mandatory_facts_fails_task_completion():
    from app.models.entities import Run
    from app.services.evaluation import evaluate_run

    gt_normal_002 = {
        "annotation_version": "1.0",
        "expected_task_completion": True,
        "supported_facts": [
            {"text": "NovaEdge 5 laptop series launched with prices starting at ₹58,990.", "evidence_ids": ["E1"]},
            {"text": "Pre-orders open on 3 November.", "evidence_ids": ["E1"]},
            {"text": "120,000 customers have pre-registered interest.", "evidence_ids": ["E1"]},
            {"text": "NovaTech plans ₹150 crore of launch marketing spend in the current fiscal year.", "evidence_ids": ["E1"]},
            {"text": "Management is targeting a 5% share of the premium laptop segment within 12 months (a target, not an achieved result).", "evidence_ids": ["E1"]},
            {"text": "No sales or revenue guidance was provided for the series.", "evidence_ids": ["E1"]},
        ],
        "contradictions": [
            {"text": "Pre-orders have already closed.", "evidence_ids": []},
            {"text": "Marketing spend is ₹1,500 crore.", "evidence_ids": []},
            {"text": "The company issued sales guidance.", "evidence_ids": []},
        ],
        "unsupported_claims": [
            {"text": "NovaTech will sell 120,000 laptops.", "evidence_ids": []},
        ],
        "missing_information": [],
    }

    record_normal_002 = {
        "scenario_id": "NORMAL-002",
        "category": "normal",
        "input": {
            "evidence": [{
                "evidence_id": "E1",
                "content": "NovaTech launched its NovaEdge 5 laptop series today, with prices starting at ₹58,990. Pre-orders open on 3 November, and the company said 120,000 customers have pre-registered their interest. NovaTech plans to spend ₹150 crore on launch marketing during the current fiscal year, and management said it is targeting a 5% share of the premium laptop segment within 12 months. The company did not provide sales or revenue guidance for the series."
            }]
        },
        "ground_truth": gt_normal_002,
    }

    # Case 1: Incomplete run from run2 (omits starting price, pre-registrations, and 5% target)
    incomplete_output = {
        "schema_version": "1.0",
        "scenario_id": "NORMAL-002",
        "ticker": "NOVT.SYN",
        "sentiment": "neutral",
        "price_impact": "neutral",
        "recommendation": "HOLD",
        "confidence": 0.6,
        "forecast_pct": None,
        "forecast_horizon": "unspecified",
        "reasoning": [
            {"text": "NovaTech has launched the NovaEdge 5 laptop series, indicating potential market interest in their products.", "evidence_ids": ["E1"]}
        ],
        "key_factors": [
            {"text": "NovaTech targeted a launch marketing spend of ₹150 crore in the current fiscal year.", "evidence_ids": ["E1"]}
        ],
        "risk_factors": [
            {"text": "No sales or revenue forecast was provided for the newly launched series.", "evidence_ids": ["E1"]}
        ],
        "missing_information": ["Specific sales and revenue targets or forecasts for the newly launched laptop series."],
        "source_ids_used": ["E1"],
    }
    run_incomplete = Run(id="run-n2-incomplete", experiment_id="exp-1", record_index=1, status="completed", normalized_output=incomplete_output)
    eval_incomplete = evaluate_run(run_incomplete, record_normal_002, "exp-1")
    assert eval_incomplete["task_completion"]["status"] == "fail"
    assert eval_incomplete["task_completion"]["reason_codes"] == ["MISSING_MANDATORY_FACTS"]
    missing_facts = eval_incomplete["task_completion"]["requirements"]["missing_mandatory_facts"]
    assert len(missing_facts) == 3
    assert any("58,990" in f for f in missing_facts)
    assert any("120,000" in f for f in missing_facts)
    assert any("5%" in f for f in missing_facts)

    # Case 2: Complete run with all mandatory facts (omitting optional pre-order date) -> PASS
    complete_output = {
        "schema_version": "1.0",
        "scenario_id": "NORMAL-002",
        "ticker": "NOVT.SYN",
        "sentiment": "neutral",
        "price_impact": "neutral",
        "recommendation": "HOLD",
        "confidence": 0.7,
        "forecast_pct": None,
        "forecast_horizon": "short_term",
        "reasoning": [
            {"text": "NovaTech launched its NovaEdge 5 laptop series with prices starting at ₹58,990.", "evidence_ids": ["E1"]},
            {"text": "120,000 customers have pre-registered their interest.", "evidence_ids": ["E1"]},
            {"text": "The company plans to spend ₹150 crore on launch marketing during the current fiscal year.", "evidence_ids": ["E1"]},
        ],
        "key_factors": [
            {"text": "Management is targeting a 5% share of the premium laptop segment within 12 months.", "evidence_ids": ["E1"]},
        ],
        "risk_factors": [
            {"text": "No sales or revenue guidance was provided for the series.", "evidence_ids": ["E1"]},
        ],
        "missing_information": [],
        "source_ids_used": ["E1"],
    }
    run_complete = Run(id="run-n2-complete", experiment_id="exp-1", record_index=1, status="completed", normalized_output=complete_output)
    eval_complete = evaluate_run(run_complete, record_normal_002, "exp-1")
    assert eval_complete["task_completion"]["status"] == "pass"
    assert eval_complete["task_completion"]["requirements"]["missing_mandatory_facts"] == []

def test_normal_006_missing_mandatory_revenue_recognition_fails_task_completion():
    from app.models.entities import Run
    from app.services.evaluation import evaluate_run

    gt_normal_006 = {
        "annotation_version": "1.0",
        "expected_task_completion": True,
        "supported_facts": [
            {"text": "Three-year agreement for managed cybersecurity services across 2,200 branches of Meridian Bank.", "evidence_ids": ["E1"]},
            {"text": "Contract value is ₹310 crore.", "evidence_ids": ["E1"]},
            {"text": "Services begin on 1 January.", "evidence_ids": ["E1"]},
            {"text": "SecureNet said revenue will be recognised evenly over the contract term.", "evidence_ids": ["E1"]},
            {"text": "SecureNet described it as its largest single banking contract (company characterisation).", "evidence_ids": ["E1"]},
            {"text": "Meridian Bank did not comment on the terms.", "evidence_ids": ["E1"]},
        ],
        "contradictions": [
            {"text": "The contract is valued at ₹3,100 crore.", "evidence_ids": []},
        ],
        "unsupported_claims": [],
        "missing_information": [],
    }

    record_normal_006 = {
        "scenario_id": "NORMAL-006",
        "category": "normal",
        "input": {
            "evidence": [{
                "evidence_id": "E1",
                "content": "SecureNet signed a three-year agreement with Meridian Bank to provide managed cybersecurity services across the bank's 2,200 branches. The contract is valued at ₹310 crore and services begin on 1 January. SecureNet said it would recognise revenue evenly over the contract term and described the agreement as its largest single banking contract. Meridian Bank did not comment on the terms."
            }]
        },
        "ground_truth": gt_normal_006,
    }

    # Case 1: Run 2 output (has ₹310 crore and Meridian did not comment, but omits revenue recognition) -> FAIL
    omitted_rev_output = {
        "schema_version": "1.0",
        "scenario_id": "NORMAL-006",
        "ticker": "SCNT.SYN",
        "sentiment": "positive",
        "price_impact": "positive",
        "recommendation": "BUY",
        "confidence": 0.75,
        "forecast_pct": None,
        "forecast_horizon": "short_term",
        "reasoning": [
            {"text": "SecureNet signed a three-year agreement with Meridian Bank.", "evidence_ids": ["E1"]}
        ],
        "key_factors": [
            {"text": "The agreement is valued at ₹310 crore, and it is described as SecureNet's largest single banking contract.", "evidence_ids": ["E1"]}
        ],
        "risk_factors": [
            {"text": "Meridian Bank did not comment on the terms of the agreement, which could imply uncertainties or potential risks associated with the contract.", "evidence_ids": ["E1"]}
        ],
        "missing_information": [],
        "source_ids_used": ["E1"],
    }
    run_omitted = Run(id="run-n6-omitted", experiment_id="exp-1", record_index=5, status="completed", normalized_output=omitted_rev_output)
    eval_omitted = evaluate_run(run_omitted, record_normal_006, "exp-1")
    assert eval_omitted["task_completion"]["status"] == "fail"
    assert eval_omitted["task_completion"]["reason_codes"] == ["MISSING_MANDATORY_FACTS"]
    assert "SecureNet said revenue will be recognised evenly over the contract term." in eval_omitted["task_completion"]["requirements"]["missing_mandatory_facts"]

    # Case 2: Output containing contradictory value ₹3,100 crore -> FAIL with CONTRADICTION_WITH_GROUND_TRUTH
    contra_output = {
        "schema_version": "1.0",
        "scenario_id": "NORMAL-006",
        "ticker": "SCNT.SYN",
        "sentiment": "positive",
        "price_impact": "positive",
        "recommendation": "BUY",
        "confidence": 0.75,
        "forecast_pct": None,
        "forecast_horizon": "short_term",
        "reasoning": [
            {"text": "The contract is valued at ₹3,100 crore.", "evidence_ids": ["E1"]}
        ],
        "key_factors": [
            {"text": "Revenue will be recognised evenly over the contract term.", "evidence_ids": ["E1"]}
        ],
        "risk_factors": [
            {"text": "Meridian Bank did not comment on the terms.", "evidence_ids": ["E1"]}
        ],
        "missing_information": [],
        "source_ids_used": ["E1"],
    }
    run_contra = Run(id="run-n6-contra", experiment_id="exp-1", record_index=5, status="completed", normalized_output=contra_output)
    eval_contra = evaluate_run(run_contra, record_normal_006, "exp-1")
    assert eval_contra["task_completion"]["status"] == "fail"
    assert eval_contra["task_completion"]["reason_codes"] == ["CONTRADICTION_WITH_GROUND_TRUTH"]



