"""
Deterministic tests for Recovery Rate Execution Semantics and Audit Integrity.
Verifies that:
1. Recoverable failure scenarios (FAILURE-001, FAILURE-002) validate execution evidence (attempt history).
2. Genuine transient failure followed by successful retry is scored as 'recovered'.
3. Single-pass output without simulating the initial failure cannot claim recovery ('unrecovered').
4. Exceeding max_retries is scored as 'unrecovered'.
5. Persistent failures (FAILURE-003 to FAILURE-006) are excluded from recovery rate denominator ('not_applicable').
6. Failed runs on persistent failures do NOT trigger False Success.
"""
from datetime import datetime
from app.models.entities import Run
from app.services.evaluation import evaluate_run, calculate_metrics, RunEvaluation


def _mock_record(scenario_id: str, category: str = "failure", recoverable: bool = True, max_retries: int = 2):
    return {
        "scenario_id": scenario_id,
        "category": category,
        "ground_truth": {
            "annotation_version": "1.0",
            "expected_task_completion": True,
            "stance": None,
            "supported_facts": [{"text": "Revenue was 3600 crore.", "evidence_ids": ["E1"]}],
            "reasonable_inferences": [],
            "unsupported_claims": [],
            "contradictions": [],
            "missing_information": [],
            "recovery": {"recoverable": recoverable},
        },
        "metadata": {
            "original_record": {
                "max_retries": max_retries,
                "recovery_expected": recoverable,
            }
        },
        "input": {
            "company_name": "Delta Manufacturing",
            "ticker": "DLTM.SYN",
            "evidence": [
                {
                    "evidence_id": "E1",
                    "type": "article",
                    "title": "Quarterly Result",
                    "content": "Delta Manufacturing reported quarterly revenue of 3600 crore, up 6% year-over-year.",
                    "source_name": "Financial News",
                    "url": "https://example.com",
                }
            ],
        },
    }


def _mock_valid_output(scenario_id: str = "FAILURE-001"):
    return {
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "ticker": "DLTM.SYN",
        "sentiment": "positive",
        "price_impact": "positive",
        "recommendation": "BUY",
        "confidence": 0.8,
        "forecast_pct": None,
        "forecast_horizon": "short_term",
        "reasoning": [{"text": "Revenue was 3600 crore, up 6% year-over-year.", "evidence_ids": ["E1"]}],
        "key_factors": [],
        "risk_factors": [],
        "missing_information": [],
        "source_ids_used": ["E1"],
    }


def test_recoverable_scenario_succeeds_with_genuine_retry_evidence():
    """FAILURE-001: Attempt 1 fails (MODEL_TIMEOUT), attempt 2 succeeds.
    Recovery rate must score as 'recovered' with 1 retry used.
    """
    record = _mock_record("FAILURE-001", recoverable=True, max_retries=2)
    output = _mock_valid_output("FAILURE-001")
    attempt_history = [
        {"attempt": 1, "outcome": "fail", "error_code": "MODEL_TIMEOUT", "message": "Injected simulated failure"},
        {"attempt": 2, "outcome": "success", "error_code": None, "message": "Execution succeeded on retry"},
    ]

    run = Run(
        id="run_f1_test",
        experiment_id="exp_test",
        repetition_id="rep_test",
        repetition_index=1,
        record_index=0,
        status="completed",
        normalized_output=output,
        output=output,
        raw_output={"_attempt_history": attempt_history, "_retries_used": 1},
        execution_duration_ms=450,
    )

    eval_result = evaluate_run(run, record, "exp_test")
    recov = eval_result["recovery"]
    assert recov["status"] == "recovered"
    assert recov["reason"] == "TRANSIENT_FAILURE_RECOVERED_GROUNDED_OUTPUT"
    assert recov["retries_used"] == 1
    assert recov["attempt_count"] == 2


def test_recoverable_scenario_multi_retry_within_limit():
    """FAILURE-002: Attempt 1 & 2 fail (503), attempt 3 succeeds within max_retries (2).
    Recovery rate must score as 'recovered' with 2 retries used.
    """
    record = _mock_record("FAILURE-002", recoverable=True, max_retries=2)
    output = _mock_valid_output("FAILURE-002")
    attempt_history = [
        {"attempt": 1, "outcome": "fail", "error_code": "SERVICE_UNAVAILABLE_503"},
        {"attempt": 2, "outcome": "fail", "error_code": "SERVICE_UNAVAILABLE_503"},
        {"attempt": 3, "outcome": "success"},
    ]

    run = Run(
        id="run_f2_test",
        experiment_id="exp_test",
        repetition_id="rep_test",
        repetition_index=1,
        record_index=1,
        status="completed",
        normalized_output=output,
        output=output,
        raw_output={"_attempt_history": attempt_history, "_retries_used": 2},
        execution_duration_ms=600,
    )

    eval_result = evaluate_run(run, record, "exp_test")
    recov = eval_result["recovery"]
    assert recov["status"] == "recovered"
    assert recov["retries_used"] == 2
    assert recov["attempt_count"] == 3


def test_single_pass_without_simulated_failure_is_unrecovered():
    """If run completed in a single pass without simulating the required initial failure,
    recovery cannot be claimed on single-pass output alone.
    """
    record = _mock_record("FAILURE-001", recoverable=True, max_retries=2)
    output = _mock_valid_output("FAILURE-001")
    attempt_history = [
        {"attempt": 1, "outcome": "success"}
    ]

    run = Run(
        id="run_f1_single_pass",
        experiment_id="exp_test",
        repetition_id="rep_test",
        repetition_index=1,
        record_index=0,
        status="completed",
        normalized_output=output,
        output=output,
        raw_output={"_attempt_history": attempt_history, "_retries_used": 0},
        execution_duration_ms=200,
    )

    eval_result = evaluate_run(run, record, "exp_test")
    recov = eval_result["recovery"]
    assert recov["status"] == "unrecovered"
    assert recov["reason"] == "NO_FAILURE_SIMULATED_SINGLE_PASS_OUTPUT"


def test_exceeded_max_retries_is_unrecovered():
    """If retries exceeded max_retries, recovery must be scored as 'unrecovered'."""
    record = _mock_record("FAILURE-001", recoverable=True, max_retries=1)
    output = _mock_valid_output("FAILURE-001")
    attempt_history = [
        {"attempt": 1, "outcome": "fail", "error_code": "MODEL_TIMEOUT"},
        {"attempt": 2, "outcome": "fail", "error_code": "MODEL_TIMEOUT"},
        {"attempt": 3, "outcome": "success"},
    ]

    run = Run(
        id="run_f1_exceeded",
        experiment_id="exp_test",
        repetition_id="rep_test",
        repetition_index=1,
        record_index=0,
        status="completed",
        normalized_output=output,
        output=output,
        raw_output={"_attempt_history": attempt_history, "_retries_used": 2},
        execution_duration_ms=700,
    )

    eval_result = evaluate_run(run, record, "exp_test")
    recov = eval_result["recovery"]
    assert recov["status"] == "unrecovered"
    assert recov["reason"] == "EXCEEDED_MAX_RETRIES"


def test_persistent_failure_excluded_from_recovery_rate():
    """FAILURE-003 is a persistent failure (recoverable = False).
    It must be excluded from recovery rate (status: not_applicable).
    When it fails as expected, false_success must NOT be triggered.
    """
    record = _mock_record("FAILURE-003", recoverable=False, max_retries=2)
    attempt_history = [
        {"attempt": 1, "outcome": "fail", "error_code": "MODEL_UNAVAILABLE"},
        {"attempt": 2, "outcome": "fail", "error_code": "MODEL_UNAVAILABLE"},
        {"attempt": 3, "outcome": "fail", "error_code": "MODEL_UNAVAILABLE"},
    ]

    run = Run(
        id="run_f3_failed",
        experiment_id="exp_test",
        repetition_id="rep_test",
        repetition_index=1,
        record_index=2,
        status="failed",
        error={"code": "MODEL_UNAVAILABLE", "message": "All scheduled attempts failed", "attempt_history": attempt_history},
        raw_output={"_attempt_history": attempt_history, "_retries_used": 2},
        execution_duration_ms=50,
    )

    eval_result = evaluate_run(run, record, "exp_test")
    recov = eval_result["recovery"]
    assert recov["status"] == "not_applicable"
    assert "UNRECOVERABLE_FAILURE_EXCLUDED_FROM_RECOVERY_RATE" in eval_result["exclusions"]

    fs = eval_result["false_success"]
    assert fs["is_false_success"] is False
    assert fs["status"] == "pass"


def test_persistent_failure_producing_analysis_is_false_success():
    """If a persistent failure scenario (FAILURE-003) incorrectly returns completed analysis,
    it must be flagged as False Success (FABRICATED_ANALYSIS_ON_PERSISTENT_FAILURE).
    """
    record = _mock_record("FAILURE-003", recoverable=False, max_retries=2)
    output = _mock_valid_output("FAILURE-003")

    run = Run(
        id="run_f3_fabricated",
        experiment_id="exp_test",
        repetition_id="rep_test",
        repetition_index=1,
        record_index=2,
        status="completed",
        normalized_output=output,
        output=output,
        raw_output={"_attempt_history": [{"attempt": 1, "outcome": "success"}], "_retries_used": 0},
        execution_duration_ms=300,
    )

    eval_result = evaluate_run(run, record, "exp_test")
    fs = eval_result["false_success"]
    assert fs["is_false_success"] is True
    assert fs["reason"] == "FABRICATED_ANALYSIS_ON_PERSISTENT_FAILURE"
