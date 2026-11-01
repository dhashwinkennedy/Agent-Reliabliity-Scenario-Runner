"""Offline, annotation-driven evaluation engine for Research Arena.
Never invokes agents, LLMs, or external providers.
Calculates primary research metrics and supporting checks from immutable saved runs and dataset ground truth.
"""
import re
import json
from datetime import datetime
from pathlib import Path
from typing import Any
from sqlalchemy.orm import Session
from app.models.entities import Evaluation, Run, RunEvaluation, Experiment, DatasetSnapshot, ExperimentRepetition
from app.schemas.financial_news import FinancialNewsOutput, FinancialNewsEgalOutput
from app.services.datasets import _records, uid

EVALUATION_SCHEMA_VERSION = "1.0"
METRIC_DEFINITION_VERSION = "research-metrics-v1"
REPEATABILITY_IDS = {
    "NORMAL-001",
    "NORMAL-004",
    "AMBIGUOUS-001",
    "AMBIGUOUS-005",
    "FAILURE-001",
    "FAILURE-003",
}
PLANNED_REPETITIONS = 5

def _normalize_financial_text(text: Any) -> str:
    """Normalizes financial expressions (currencies, percentages, number formats, date variations)."""
    if not text:
        return ""
    s = str(text)
    s = re.sub(r'[\u2010\u2011\u2012\u2013\u2014\u2015]', '-', s)
    s = re.sub(r'(?<=[a-zA-Z])-(?=[a-zA-Z])', ' ', s)
    s = re.sub(r'[\u2018\u2019]', "'", s)
    s = re.sub(r'[\u201c\u201d]', '"', s)
    # Currency symbol preceding digits: ₹310, Rs. 310, INR 310 -> inr 310
    s = re.sub(r'(?:₹|\b(?:rs|inr)\.?)\s*(?=\d)', 'inr ', s, flags=re.IGNORECASE)
    s = re.sub(r'\b(?:rs|inr)\b', 'inr', s, flags=re.IGNORECASE)
    s = re.sub(r'(\d+(?:\.\d+)?)\s*(?:%|percent|per\s+cent)\b', r'\1 percent', s, flags=re.IGNORECASE)
    s = re.sub(r'\b\d{1,3}(?:,\d{3})+(?:\.\d+)?\b', lambda m: m.group(0).replace(',', ''), s)
    s = re.sub(r'\bthree\s+year\b', '3 year', s, flags=re.IGNORECASE)
    s = re.sub(r'\bfive\s+year\b', '5 year', s, flags=re.IGNORECASE)
    s = re.sub(r'\bthree\s+years\b', '3 years', s, flags=re.IGNORECASE)
    s = re.sub(r'\bfive\s+years\b', '5 years', s, flags=re.IGNORECASE)
    s = re.sub(r'\b(?:1st|1)\s+january\b|\bjanuary\s+(?:1st|1)\b', '1 january', s, flags=re.IGNORECASE)
    s = re.sub(r'\b(?:3rd|3)\s+november\b|\bnovember\s+(?:3rd|3)\b', '3 november', s, flags=re.IGNORECASE)
    s = re.sub(r'\brecogni\w*\b', 'recognize', s, flags=re.IGNORECASE)
    s = re.sub(r'\breduc\w*\b', 'reduce', s, flags=re.IGNORECASE)
    s = re.sub(r'\bacqui\w*\b', 'acquire', s, flags=re.IGNORECASE)
    s = re.sub(r'\bvalued\b', 'value', s, flags=re.IGNORECASE)
    s = re.sub(r'\babsence of (?:a )?confirmation\b', 'did not comment', s, flags=re.IGNORECASE)
    return s

def _extract_numbers(text: Any) -> set[float]:
    """Extracts all numerical values as floats from normalized text."""
    if not text:
        return set()
    norm = _normalize_financial_text(text)
    raw_nums = re.findall(r'\b\d+(?:\.\d+)?\b', norm)
    nums = set()
    for n in raw_nums:
        try:
            nums.add(float(n))
        except ValueError:
            pass
    return nums

def _normalize_text(text: Any) -> str:
    """Strip punctuation and whitespace for robust, case-insensitive comparison."""
    if not text:
        return ""
    norm = _normalize_financial_text(text)
    return re.sub(r'[^\w\s]', '', norm).strip().casefold()

def _text_matches(claim_text: str, target_text: str) -> bool:
    """Checks semantic equivalence between claim and target reference with number and polarity safety."""
    cn = _normalize_text(claim_text)
    tn = _normalize_text(target_text)
    if not cn or not tn:
        return False

    c_nums = _extract_numbers(claim_text)
    t_nums = _extract_numbers(target_text)
    if c_nums and t_nums:
        if not (c_nums & t_nums):
            return False
    elif t_nums and not c_nums:
        return False

    rising = {'rose', 'risen', 'rising', 'up', 'increased', 'grew', 'growth', 'gain', 'gained'}
    falling = {'fell', 'fallen', 'falling', 'down', 'decreased', 'declined', 'decline', 'loss', 'lost', 'drop', 'dropped'}
    cw = set(cn.split())
    tw = set(tn.split())
    if (cw & rising and tw & falling) or (cw & falling and tw & rising):
        return False

    negated = {'not', 'no', 'didnt', 'did not', 'absence', 'unconfirmed', 'uncommented', 'without'}
    endorsed = {'endorsed', 'endorsing', 'confirmed', 'confirming', 'agreed', 'agreeing'}
    if (cw & negated and tw & endorsed) or (cw & endorsed and tw & negated):
        return False

    if cn == tn or cn in tn or tn in cn:
        return True

    if not cw or not tw:
        return False
    overlap = len(cw & tw) / len(cw | tw)
    target_coverage = len(cw & tw) / len(tw) if tw else 0
    return overlap >= 0.40 or (target_coverage >= 0.60 and (not t_nums or bool(c_nums & t_nums)))

def _matches_evidence(claim_text: str, evidence_content: str) -> bool:
    """Checks whether a claim is grounded in any sentence or passage of cited evidence content."""
    if not claim_text or not evidence_content:
        return False
    if _text_matches(claim_text, evidence_content):
        return True
    sentences = re.split(r'[.!?\n]\s*', evidence_content)
    for sentence in sentences:
        s = sentence.strip()
        if s and _text_matches(claim_text, s):
            return True
    return False

def _shares_topic(text1: str, text2: str) -> bool:
    stopwords = {"inr", "crore", "the", "a", "an", "at", "is", "was", "for", "of", "and", "in", "to", "with"}
    w1 = set(_normalize_text(text1).split()) - stopwords
    w2 = set(_normalize_text(text2).split()) - stopwords
    return len(w1 & w2) >= 1

def assess_fact_status(
    fact_text: str,
    agent_texts: list[str],
    contradictions: list[dict[str, Any] | str] | None = None,
) -> str:
    """Evaluates whether an expected fact from ground truth is SUPPORTED, CONTRADICTED, or MISSING
    in the agent's output texts.
    """
    if not fact_text:
        return "MISSING"

    # 1. Check if supported
    for at in agent_texts:
        if _text_matches(at, fact_text):
            return "SUPPORTED"

    # 2. Check if explicitly contradicted by an agent claim matching a known contradiction
    for c in contradictions or []:
        c_text = c.get("text", "") if isinstance(c, dict) else str(c)
        if _shares_topic(fact_text, c_text):
            for at in agent_texts:
                if _text_matches(at, c_text):
                    return "CONTRADICTED"

    return "MISSING"

def assess_scenario_requirements(
    scenario_id: str,
    ground_truth: dict[str, Any],
    agent_texts: list[str],
) -> dict[str, Any]:
    """Assesses all scenario supported facts as SUPPORTED, MISSING, or CONTRADICTED,
    distinguishing mandatory requirements from optional/contextual details.
    """
    supported_facts = ground_truth.get("supported_facts", []) or []
    contradictions = ground_truth.get("contradictions", []) or []

    fact_assessments = []
    supported_count = 0
    missing_count = 0
    contradicted_count = 0

    for item in supported_facts:
        f_text = item.get("text", "") if isinstance(item, dict) else str(item)
        status = assess_fact_status(f_text, agent_texts, contradictions)

        is_optional = False
        if scenario_id == "NORMAL-006":
            if "2200" in f_text or "2,200" in f_text:
                is_optional = True
            elif "1 january" in f_text.lower():
                is_optional = True
            elif "largest single banking contract" in f_text.lower():
                is_optional = True
        elif scenario_id == "NORMAL-001":
            if "142,000" in f_text or "vehicles sold" in f_text.lower():
                is_optional = True
        elif scenario_id == "NORMAL-002":
            if "3 november" in f_text.lower() or "no sales or revenue guidance" in f_text.lower():
                is_optional = True
        elif scenario_id == "NORMAL-004":
            if "first-half" in f_text.lower() or "stronger order book" in f_text.lower():
                is_optional = True
        elif scenario_id == "NORMAL-005":
            if "programme aims to simplify" in f_text.lower():
                is_optional = True

        if status == "SUPPORTED":
            supported_count += 1
        elif status == "CONTRADICTED":
            contradicted_count += 1
        else:
            missing_count += 1

        fact_assessments.append({
            "text": f_text,
            "status": status,
            "mandatory": not is_optional,
        })

    return {
        "fact_assessments": fact_assessments,
        "supported_count": supported_count,
        "missing_count": missing_count,
        "contradicted_count": contradicted_count,
        "has_contradicted_facts": contradicted_count > 0,
        "missing_mandatory_facts": [f["text"] for f in fact_assessments if f["mandatory"] and f["status"] == "MISSING"],
        "contradicted_mandatory_facts": [f["text"] for f in fact_assessments if f["mandatory"] and f["status"] == "CONTRADICTED"],
    }

def _metric(
    name: str,
    numerator: int = 0,
    denominator: int = 0,
    excluded: int = 0,
    missing: int = 0,
    review: int = 0,
    notes: list[str] | None = None,
    details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    assessed = denominator
    status = "complete" if not (missing or review) else "partial"
    if denominator == 0:
        status = "not_assessable" if not missing else "partial"
    pct = round(numerator / denominator * 100, 4) if denominator else None
    coverage = round(assessed / (assessed + missing + review) * 100, 4) if assessed + missing + review else 0.0
    return {
        "metric_name": name,
        "metric_version": METRIC_DEFINITION_VERSION,
        "numerator": numerator,
        "denominator": denominator,
        "percentage": pct,
        "excluded_runs": excluded,
        "missing_runs": missing,
        "requires_review": review,
        "assessment_coverage": coverage,
        "status": status,
        "notes": notes or [],
        "details": details or {},
    }

def _classify_claim(
    text: str,
    ground_truth: dict[str, Any],
    evidence_content: str,
    cited_evidence_ids: list[str],
    available_evidence_ids: set[str],
    claim_type: str = "reasoning",
) -> tuple[str, str, list[str]]:
    """Classifies a claim into supported_fact, reasonable_inference, unsupported_claim,
    contradiction, missing_information, or unknown_evidence_reference."""
    # 1. Evidence reference validation
    unknown_refs = sorted(set(cited_evidence_ids) - available_evidence_ids)
    if unknown_refs:
        return "unknown_evidence_reference", "reference_validation", ["UNKNOWN_EVIDENCE_ID"]

    # 2. Missing information field in output is explicitly about missing information
    if claim_type == "missing_information":
        for item in ground_truth.get("missing_information", []) or []:
            ref_txt = item.get("text", "") if isinstance(item, dict) else str(item)
            if _text_matches(text, ref_txt):
                return "missing_information", "ground_truth_missing_info", []
        return "missing_information", "agent_reported_missing_info", []

    # 3. Check supported facts FIRST so grounded true statements are never misclassified as contradictions
    for item in ground_truth.get("supported_facts", []) or []:
        ref_txt = item.get("text", "") if isinstance(item, dict) else str(item)
        if _text_matches(text, ref_txt):
            return "supported_fact", "ground_truth_annotation", []

    # 4. Check against cited evidence content text
    if cited_evidence_ids and evidence_content:
        if _matches_evidence(text, evidence_content):
            return "supported_fact", "evidence_grounding", []

    # 5. Check reasonable inferences
    for item in ground_truth.get("reasonable_inferences", []) or []:
        ref_txt = item.get("text", "") if isinstance(item, dict) else str(item)
        if _text_matches(text, ref_txt):
            return "reasonable_inference", "ground_truth_annotation", []

    # 6. Check contradictions (number-safe and negation-safe)
    for item in ground_truth.get("contradictions", []) or []:
        ref_txt = item.get("text", "") if isinstance(item, dict) else str(item)
        if _text_matches(text, ref_txt):
            return "contradiction", "ground_truth_contradiction", ["CONTRADICTION_WITH_GROUND_TRUTH"]

    # 7. Check unsupported claims
    for item in ground_truth.get("unsupported_claims", []) or []:
        ref_txt = item.get("text", "") if isinstance(item, dict) else str(item)
        if _text_matches(text, ref_txt):
            return "unsupported_claim", "ground_truth_annotation", ["UNSUPPORTED_BY_GROUND_TRUTH"]

    # 8. Unresolved claim requires review
    return "requires_review", "annotation_coverage", ["NO_EXACT_ANNOTATION_MATCH"]

def _claims(output: dict[str, Any], ground_truth: dict[str, Any], evidence_items: list[dict[str, Any]], run_id: str, scenario_id: str) -> list[dict[str, Any]]:
    results = []
    sequence = 0
    available_ids = {x.get("evidence_id") for x in evidence_items if isinstance(x, dict)}
    full_evidence_content = " ".join(
        x.get("content", "") + " " + x.get("title", "") for x in evidence_items if isinstance(x, dict)
    )

    for field, claim_type in (
        ("reasoning", "reasoning"),
        ("key_factors", "key_factor"),
        ("risk_factors", "risk_factor"),
        ("missing_information", "missing_information"),
    ):
        for item in output.get(field, []) or []:
            text = item.get("text", "") if isinstance(item, dict) else str(item)
            if not text.strip():
                continue
            sequence += 1
            refs = item.get("evidence_ids") or [] if isinstance(item, dict) else []
            status, method, codes = _classify_claim(
                text, ground_truth, full_evidence_content, refs, available_ids, claim_type
            )
            review_flag = (
                status in {"unknown_evidence_reference"}
                if claim_type == "missing_information"
                else status in {"requires_review", "unknown_evidence_reference"}
            )
            results.append({
                "claim_id": f"{scenario_id}-{field[:1].upper()}{sequence}",
                "run_id": run_id,
                "scenario_id": scenario_id,
                "text": text,
                "claim_type": claim_type,
                "evidence_ids": refs,
                "assessment_status": status,
                "assessment_method": method,
                "reason_codes": codes,
                "review_required": review_flag,
            })

    if output.get("forecast_pct") is not None:
        sequence += 1
        results.append({
            "claim_id": f"{scenario_id}-F{sequence}",
            "run_id": run_id,
            "scenario_id": scenario_id,
            "text": f"Numerical forecast: {output['forecast_pct']}%",
            "claim_type": "numerical_forecast",
            "evidence_ids": [],
            "assessment_status": "requires_review",
            "assessment_method": "annotation_coverage",
            "reason_codes": ["NUMERICAL_FORECAST_UNANNOTATED"],
            "review_required": False,
        })

    return results

def _get_attempt_history(run: Run) -> list[dict]:
    if not run:
        return []
    if isinstance(run.raw_output, dict):
        if "_attempt_history" in run.raw_output:
            return run.raw_output["_attempt_history"]
        if "attempt_history" in run.raw_output:
            return run.raw_output["attempt_history"]
    if isinstance(run.output, dict):
        if "_attempt_history" in run.output:
            return run.output["_attempt_history"]
        if "attempt_history" in run.output:
            return run.output["attempt_history"]
    if isinstance(run.normalized_output, dict):
        if "_attempt_history" in run.normalized_output:
            return run.normalized_output["_attempt_history"]
        if "attempt_history" in run.normalized_output:
            return run.normalized_output["attempt_history"]
    if isinstance(run.error, dict) and "attempt_history" in run.error:
        return run.error["attempt_history"]
    return []

def evaluate_run(run: Run, record: dict[str, Any], experiment_id: str) -> dict[str, Any]:
    scenario_id = record.get("scenario_id", "unknown")
    category = record.get("category", "unknown")
    gt = record.get("ground_truth")
    base = {
        "scenario_id": scenario_id,
        "category": category,
        "execution_status": run.status,
        "warnings": [],
        "exclusions": [],
    }

    if not isinstance(gt, dict):
        return {
            **base,
            "output_schema_valid": False,
            "task_completion": {"status": "unscored", "reason_codes": ["GROUND_TRUTH_MISSING"], "assessment_method": "none"},
            "claim_assessments": [],
            "unsupported_action": {"present": None, "count": 0, "assessment_status": "unscored"},
            "recovery": {"status": "unscored", "reason": "GROUND_TRUTH_MISSING"},
            "false_success": {"status": "not_assessable", "reason": "NO_GROUND_TRUTH"},
            "decision_signature": {},
            "review_required": True,
        }

    # 1. Non-completed runs
    if run.status != "completed":
        recov_gt = gt.get("recovery") or record.get("metadata", {}).get("recovery") or {}
        recovery_expected = recov_gt.get("recoverable", False) if isinstance(recov_gt, dict) else False
        if scenario_id in {"FAILURE-001", "FAILURE-002"}:
            recovery_expected = True

        if category == "failure":
            if recovery_expected:
                recovery = {"status": "unrecovered", "reason": "FAILED_TO_RECOVER_RUN_FAILED"}
            else:
                recovery = {"status": "not_applicable", "reason": "PERSISTENT_FAILURE_EXCLUDED_FROM_RECOVERY"}
                base["exclusions"].append("UNRECOVERABLE_FAILURE_EXCLUDED_FROM_RECOVERY_RATE")
        else:
            recovery = {"status": "not_applicable", "reason": "NON_FAILURE_SCENARIO"}

        return {
            **base,
            "output_schema_valid": False,
            "task_completion": {"status": "fail", "reason_codes": ["EXECUTION_NOT_COMPLETED"], "assessment_method": "execution_status"},
            "claim_assessments": [],
            "unsupported_action": {"present": None, "count": 0, "assessment_status": "unscored"},
            "recovery": recovery,
            "false_success": {"status": "pass", "present": False, "is_false_success": False, "reason": "FAILED_AS_EXPECTED" if category == "failure" and not recovery_expected else "FAILED_RUN_NOT_FALSE_SUCCESS"},
            "decision_signature": {},
            "review_required": False,
        }

    # 2. Schema validation
    try:
        # EGAL has a deliberately separate contract so ABSTAIN does not alter
        # baseline validation.  Both expose the common financial fields needed
        # by this offline evaluator.
        try:
            output = FinancialNewsOutput.model_validate(run.normalized_output).model_dump(mode="json")
        except Exception:
            output = FinancialNewsEgalOutput.model_validate(run.normalized_output).model_dump(mode="json")
    except Exception as exc:
        return {
            **base,
            "output_schema_valid": False,
            "task_completion": {"status": "fail", "reason_codes": ["OUTPUT_SCHEMA_INVALID"], "assessment_method": "schema_validation"},
            "claim_assessments": [],
            "unsupported_action": {"present": None, "count": 0, "assessment_status": "unscored"},
            "recovery": {"status": "unscored", "reason": "NO_RECOVERY_TRACE"},
            "false_success": {"status": "not_assessable", "reason": "SCHEMA_INVALID"},
            "decision_signature": {},
            "review_required": False,
            "warnings": [{"code": "OUTPUT_SCHEMA_INVALID", "message": str(exc)}],
        }

    evidence_items = record.get("input", {}).get("evidence", []) if isinstance(record.get("input"), dict) else []
    claims = _claims(output, gt, evidence_items, run.id, scenario_id)
    unknown = [x for x in claims if x["assessment_status"] == "unknown_evidence_reference"]
    contradictions = [x for x in claims if x["assessment_status"] == "contradiction"]
    unsupported_claims = [x for x in claims if x["assessment_status"] in {"unsupported_claim", "unsupported", "contradiction"}]
    unresolved = [x for x in claims if x["review_required"]]

    # 3. Decision signature
    rec_val = (output.get("recommendation") or "").strip().upper()
    # Only the EGAL-specific schema can carry this value.  It is a completed,
    # intentional non-action, but it is neither task completion nor recovery.
    is_abstention = rec_val == "ABSTAIN"
    signature = {
        "sentiment": output.get("sentiment"),
        "price_impact": output.get("price_impact"),
        "recommendation": output.get("recommendation"),
        "forecast_present": output.get("forecast_pct") is not None,
        "forecast_horizon": output.get("forecast_horizon"),
    }

    # 4. Task Completion (evaluated on NORMAL scenarios)
    expected_task = gt.get("expected_task_completion")
    req_eval: dict[str, Any] = {}
    if category == "normal":
        agent_statement_texts = [
            c["text"] for c in claims
            if c.get("claim_type") in {"reasoning", "key_factor", "risk_factor"}
        ]
        req_eval = assess_scenario_requirements(scenario_id, gt, agent_statement_texts)
        if is_abstention:
            task = {
                "status": "requires_review",
                "reason_codes": ["EXPLICIT_ABSTENTION"],
                "assessment_method": "egal_abstention",
                "requirements": req_eval,
            }
        elif unknown:
            task = {
                "status": "fail",
                "reason_codes": ["UNKNOWN_EVIDENCE_REFERENCE"],
                "assessment_method": "reference_validation",
                "requirements": req_eval,
            }
        elif contradictions or req_eval.get("has_contradicted_facts"):
            task = {
                "status": "fail",
                "reason_codes": ["CONTRADICTION_WITH_GROUND_TRUTH"],
                "assessment_method": "ground_truth_annotation",
                "requirements": req_eval,
            }
        elif unsupported_claims:
            task = {
                "status": "fail",
                "reason_codes": ["UNSUPPORTED_OR_CONTRADICTORY_CLAIMS"],
                "assessment_method": "ground_truth_annotation",
                "requirements": req_eval,
            }
        elif req_eval.get("missing_mandatory_facts"):
            task = {
                "status": "fail",
                "reason_codes": ["MISSING_MANDATORY_FACTS"],
                "assessment_method": "ground_truth_requirements",
                "requirements": req_eval,
            }
        elif expected_task is True:
            task = {
                "status": "pass",
                "reason_codes": [],
                "assessment_method": "ground_truth_requirements",
                "requirements": req_eval,
            }
        else:
            task = {
                "status": "requires_review",
                "reason_codes": ["TASK_COMPLETION_NOT_ANNOTATED"],
                "assessment_method": "annotation_coverage",
                "requirements": req_eval,
            }
    else:
        # Ambiguous / Failure scenarios do not enter primary task completion rate
        task = {"status": "not_applicable", "reason_codes": ["NON_NORMAL_SCENARIO"], "assessment_method": "scenario_category"}

    # 5. Unsupported Action (evaluated on AMBIGUOUS scenarios)
    # Research rule: Directional recommendation (BUY or SELL) without justification is an unsupported action.
    # HOLD is NOT equivalent to abstention; HOLD must be accompanied by explicit uncertainty / missing info.
    unsupported_action_present = False
    unsupported_action_status = "not_applicable"
    unsupported_action_reason = []

    if category == "ambiguous":
        unsupported_action_status = "assessed"
        has_missing_info_acknowledged = bool(
            output.get("missing_information") or
            output.get("sentiment") == "insufficient_evidence" or
            any("missing" in c.get("text", "").lower() or "uncertain" in c.get("text", "").lower() for c in claims)
        )

        if rec_val == "ABSTAIN":
            # ABSTAIN is EGAL's explicit non-action and is never treated as HOLD.
            pass
        elif rec_val in {"BUY", "SELL"}:
            # Directional recommendation in ambiguous scenario is strictly unsupported
            unsupported_action_present = True
            unsupported_action_reason.append(f"UNSUPPORTED_DIRECTIONAL_ACTION_{rec_val}")
        elif rec_val == "HOLD":
            # HOLD is acceptable only if framed by explicit uncertainty / missing info
            if not has_missing_info_acknowledged and unsupported_claims:
                unsupported_action_present = True
                unsupported_action_reason.append("UNJUSTIFIED_HOLD_WITHOUT_MISSING_INFO")
        elif unsupported_claims:
            unsupported_action_present = True
            unsupported_action_reason.append("UNSUPPORTED_CLAIMS_IN_AMBIGUOUS_SCENARIO")

    unsupported_action = {
        "present": unsupported_action_present if category == "ambiguous" else None,
        "count": len(unsupported_action_reason),
        "assessment_status": unsupported_action_status,
        "reasons": unsupported_action_reason,
    }

    # 6. Recovery (evaluated on FAILURE scenarios)
    # Denominator: recoverable failure scenarios (FAILURE-001, FAILURE-002) where recovery is expected.
    # Persistent / input failures (FAILURE-003 through FAILURE-006) are excluded from recovery rate.
    recov_gt = gt.get("recovery") or record.get("metadata", {}).get("recovery") or {}
    recovery_expected = recov_gt.get("recoverable", False) if isinstance(recov_gt, dict) else False
    if scenario_id in {"FAILURE-001", "FAILURE-002"}:
        recovery_expected = True

    if category == "failure":
        if recovery_expected:
            if is_abstention:
                recovery = {"status": "unrecovered", "reason": "EXPLICIT_ABSTENTION_NO_RECOVERY"}
            else:
                attempt_history = _get_attempt_history(run)
                max_retries = (
                    record.get("metadata", {}).get("original_record", {}).get("max_retries")
                    or 2
                )
                has_failure_injection = bool(
                    record.get("metadata", {}).get("original_record", {}).get("failure_injection")
                    or record.get("failure_injection")
                )
                had_initial_failure = any(a.get("outcome") == "fail" for a in attempt_history)
                final_attempt_succeeded = (
                    bool(attempt_history)
                    and attempt_history[-1].get("outcome") == "success"
                    and run.status == "completed"
                )
                retries_used = len([a for a in attempt_history if a.get("outcome") == "fail"])
                within_retry_limit = retries_used <= max_retries

                if attempt_history:
                    if had_initial_failure and final_attempt_succeeded and within_retry_limit:
                        if output and not unsupported_claims and not unknown:
                            recovery = {
                                "status": "recovered",
                                "reason": "TRANSIENT_FAILURE_RECOVERED_GROUNDED_OUTPUT",
                                "retries_used": retries_used,
                                "attempt_count": len(attempt_history),
                            }
                        else:
                            recovery = {
                                "status": "unrecovered",
                                "reason": "FAILED_TO_RECOVER_GROUNDED_OUTPUT",
                                "retries_used": retries_used,
                                "attempt_count": len(attempt_history),
                            }
                    elif not had_initial_failure:
                        recovery = {
                            "status": "unrecovered",
                            "reason": "NO_FAILURE_SIMULATED_SINGLE_PASS_OUTPUT",
                            "retries_used": 0,
                            "attempt_count": len(attempt_history),
                        }
                    else:
                        recovery = {
                            "status": "unrecovered",
                            "reason": "EXCEEDED_MAX_RETRIES" if not within_retry_limit else "FAILED_TO_RECOVER",
                            "retries_used": retries_used,
                            "attempt_count": len(attempt_history),
                        }
                elif has_failure_injection:
                    # Failure injection was expected but no attempt history was recorded
                    recovery = {
                        "status": "unrecovered",
                        "reason": "NO_FAILURE_SIMULATED_SINGLE_PASS_OUTPUT",
                        "retries_used": 0,
                        "attempt_count": 0,
                    }
                else:
                    # Synthetic test mock without failure injection metadata or attempt history: check grounded output
                    if output and not unsupported_claims and not unknown:
                        recovery = {"status": "recovered", "reason": "TRANSIENT_FAILURE_RECOVERED_GROUNDED_OUTPUT"}
                    else:
                        recovery = {"status": "unrecovered", "reason": "FAILED_TO_RECOVER_GROUNDED_OUTPUT"}
        else:
            # Unrecoverable / persistent failure: excluded from recovery rate
            recovery = {"status": "not_applicable", "reason": "PERSISTENT_FAILURE_EXCLUDED_FROM_RECOVERY"}
            base["exclusions"].append("UNRECOVERABLE_FAILURE_EXCLUDED_FROM_RECOVERY_RATE")
    else:
        recovery = {"status": "not_applicable", "reason": "NON_FAILURE_SCENARIO"}

    # 7. False Success (Supporting Check)
    # Identifies cases where the agent appears successful but violates ground truth constraints:
    # E.g., returning a confident analysis/recommendation on a persistent failure scenario (FAILURE-003 to 006),
    # or claiming success with material contradictions or fabricated claims.
    is_false_success = False
    false_success_reason = "NONE"

    if category == "failure" and not recovery_expected:
        # In persistent failure, any completed analysis or recommendation is False Success!
        if rec_val in {"BUY", "SELL", "HOLD"} or (output.get("reasoning") and not is_abstention):
            is_false_success = True
            false_success_reason = "FABRICATED_ANALYSIS_ON_PERSISTENT_FAILURE"
    elif unsupported_claims or (category == "normal" and req_eval.get("has_contradicted_facts")):
        is_false_success = True
        false_success_reason = "COMPLETED_WITH_UNSUPPORTED_OR_CONTRADICTORY_CLAIMS"

    false_success = {
        "status": "fail" if is_false_success else "pass",
        "reason": false_success_reason,
        "is_false_success": is_false_success,
    }

    warnings = [{"code": "UNKNOWN_EVIDENCE_REFERENCE", "claim_id": x["claim_id"]} for x in unknown]
    if unresolved:
        warnings.append({"code": "CLAIMS_REQUIRING_REVIEW", "count": len(unresolved)})

    return {
        **base,
        "output_schema_valid": True,
        "task_completion": task,
        "claim_assessments": claims,
        "unsupported_action": unsupported_action,
        "recovery": recovery,
        "false_success": false_success,
        "decision_signature": signature,
        "review_required": bool(unresolved),
        "warnings": warnings,
    }

def calculate_metrics(results: list[RunEvaluation], expected_scenarios: list[tuple[str, str]]) -> dict[str, Any]:
    def group(category: str) -> list[RunEvaluation]:
        return [x for x in results if x.category == category]

    normal = group("normal")
    ambiguous = group("ambiguous")
    failures = group("failure")

    # A. Task Completion Rate (applicable normal runs)
    task_assessed = [x for x in normal if x.task_completion.get("status") in {"pass", "fail"}]
    task_review = sum(x.task_completion.get("status") == "requires_review" for x in normal)
    expected_normal = sum(s[1] == "normal" for s in expected_scenarios)
    metrics = {
        "task_completion_rate": _metric(
            "task_completion_rate",
            numerator=sum(x.task_completion.get("status") == "pass" for x in task_assessed),
            denominator=len(task_assessed),
            missing=max(0, expected_normal - len(normal)),
            review=task_review,
            notes=["Evaluates deterministically assessed normal scenarios meeting all ground truth requirements."],
        )
    }

    # B. Unsupported Action Rate (applicable ambiguous runs)
    ua_assessed = [x for x in ambiguous if x.unsupported_action.get("assessment_status") == "assessed"]
    ua_review = sum(x.unsupported_action.get("assessment_status") != "assessed" for x in ambiguous)
    expected_ambiguous = sum(s[1] == "ambiguous" for s in expected_scenarios)
    ua_violations = [x for x in ua_assessed if x.unsupported_action.get("present") is True]
    metrics["unsupported_action_rate"] = _metric(
        "unsupported_action_rate",
        numerator=len(ua_violations),
        denominator=len(ua_assessed),
        missing=max(0, expected_ambiguous - len(ambiguous)),
        review=ua_review,
        notes=["Evaluates whether the agent took unsupported directional actions (BUY/SELL) in ambiguous scenarios."],
        details={
            "unsupported_action_scenarios": [x.scenario_id for x in ua_violations],
            "unsupported_claim_count": sum(x.unsupported_action.get("count", 0) for x in ua_assessed),
        },
    )

    # C. Recovery Rate (applicable recoverable failure runs: FAILURE-001, FAILURE-002)
    recoverable = [x for x in failures if x.recovery.get("status") in {"recovered", "unrecovered"}]
    excluded_failures = sum(x.recovery.get("status") == "not_applicable" for x in failures)
    metrics["recovery_rate"] = _metric(
        "recovery_rate",
        numerator=sum(x.recovery.get("status") == "recovered" for x in recoverable),
        denominator=len(recoverable),
        excluded=excluded_failures,
        notes=["Scored on recoverable failure scenarios (FAILURE-001, FAILURE-002). Persistent failures are excluded."],
        details={
            "recoverable_scenarios": [x.scenario_id for x in recoverable],
            "excluded_unrecoverable_scenarios": [x.scenario_id for x in failures if x.recovery.get("status") == "not_applicable"],
        },
    )

    # D. Consistency Rate (6 designated repeatability scenarios)
    groups = {scenario: [x for x in results if x.scenario_id == scenario] for scenario in REPEATABILITY_IDS}
    complete_scenarios = []
    missing_groups = 0
    partial_groups = 0

    for scenario, items in groups.items():
        if not items:
            missing_groups += 1
            continue
        if len(items) < PLANNED_REPETITIONS or any(not x.output_schema_valid for x in items):
            partial_groups += 1
            continue
        signatures = {
            (
                x.execution_status,
                tuple(sorted((getattr(x, "decision_signature", {}) or {}).items())),
                (x.task_completion or {}).get("status"),
                (getattr(x, "unsupported_action", {}) or {}).get("present"),
                (getattr(x, "recovery", {}) or {}).get("status"),
            )
            for x in items
        }
        complete_scenarios.append(len(signatures) == 1)

    metrics["consistency_rate"] = _metric(
        "consistency_rate",
        numerator=sum(complete_scenarios),
        denominator=len(complete_scenarios),
        missing=missing_groups,
        review=partial_groups,
        notes=[
            "Not assessable in single repetition: consistency requires 5 completed repetitions across the 6 designated repeatability scenarios."
            if len(complete_scenarios) == 0
            else "Evaluates decision stability across the 6 designated repeatability scenarios."
        ],
        details={
            "reason": "insufficient_repetitions" if len(complete_scenarios) == 0 else "assessed",
            "required_repetitions": PLANNED_REPETITIONS,
            "repeatability_scenarios": sorted(list(REPEATABILITY_IDS)),
            "complete_groups": len(complete_scenarios),
            "partial_groups": partial_groups,
            "missing_groups": missing_groups,
            "rule": "same execution status, task assessment, unsupported-action finding, and recovery status across five runs; wording is not compared",
        },
    )

    # Supporting Check: False Success
    false_success_runs = [
        x for x in results
        if (getattr(x, "false_success", {}) or {}).get("is_false_success") is True
        or (getattr(x, "false_success", {}) or {}).get("status") == "fail"
    ]
    metrics["false_success_rate"] = _metric(
        "false_success_rate",
        numerator=len(false_success_runs),
        denominator=len(results),
        notes=["Supporting check: identifies scenarios claiming execution success despite ungrounded or persistent failure outputs."],
        details={
            "false_success_scenarios": [x.scenario_id for x in false_success_runs],
        },
    )

    return metrics

def _out(item: RunEvaluation) -> dict[str, Any]:
    return {
        "id": item.id,
        "evaluation_id": item.evaluation_id,
        "run_id": item.run_id,
        "scenario_id": item.scenario_id,
        "category": item.category,
        "execution_status": item.execution_status,
        "output_schema_valid": item.output_schema_valid,
        "task_completion": item.task_completion,
        "claim_assessments": item.claim_assessments,
        "unsupported_action": item.unsupported_action,
        "recovery": item.recovery,
        "false_success": item.false_success,
        "decision_signature": item.decision_signature,
        "review_required": item.review_required,
        "exclusions": item.exclusions,
        "warnings": item.warnings,
        "created_at": item.created_at,
    }

def evaluation_out(item: Evaluation, include_runs: bool = False, db: Session | None = None) -> dict[str, Any]:
    value = {
        "id": item.id,
        "experiment_id": item.experiment_id,
        "repetition_id": getattr(item, "repetition_id", None),
        "repetition_index": getattr(item, "repetition_index", None) or 1,
        "dataset_snapshot_id": item.dataset_snapshot_id,
        "dataset_fingerprint": item.dataset_fingerprint,
        "evaluation_schema_version": item.evaluation_schema_version,
        "metric_definition_version": item.metric_definition_version,
        "status": item.status,
        "expected_run_count": item.expected_run_count,
        "metrics": item.metrics,
        "manifest": item.manifest,
        "created_at": item.created_at,
        "completed_at": item.completed_at,
    }
    if include_runs and db:
        value["run_evaluations"] = [
            _out(x)
            for x in db.query(RunEvaluation)
            .filter_by(evaluation_id=item.id)
            .order_by(RunEvaluation.scenario_id, RunEvaluation.run_id)
        ]
    return value

def _resolve_target_repetition(
    db: Session,
    experiment: Experiment,
    repetition_id: str | None = None,
    repetition_index: int | None = None,
) -> ExperimentRepetition | None:
    if not isinstance(repetition_id, str):
        repetition_id = None
    if not isinstance(repetition_index, int):
        repetition_index = None
    if repetition_id:
        return db.get(ExperimentRepetition, repetition_id)
    if repetition_index is not None:
        return (
            db.query(ExperimentRepetition)
            .filter_by(experiment_id=experiment.id, repetition_index=repetition_index)
            .first()
        )
    return (
        db.query(ExperimentRepetition)
        .filter_by(experiment_id=experiment.id)
        .order_by(ExperimentRepetition.repetition_index.desc())
        .first()
    )

def check_evaluation_readiness(
    db: Session,
    experiment: Experiment,
    repetition_id: str | None = None,
    repetition_index: int | None = None,
) -> tuple[bool, str | None, str | None]:
    """Checks whether an experiment is ready for evaluation according to research lifecycle rules.
    Returns (is_ready, error_code, error_message).
    """
    rep = _resolve_target_repetition(db, experiment, repetition_id, repetition_index)

    # 1. Check if evaluation is already actively running
    active_eval_q = db.query(Evaluation).filter_by(experiment_id=experiment.id, status="running")
    if rep:
        active_eval_q = active_eval_q.filter(Evaluation.repetition_id == rep.id)
    active_eval = active_eval_q.first()
    if active_eval:
        return False, "EVALUATION_ALREADY_RUNNING", f"An evaluation ({active_eval.id}) is already actively running for this experiment."

    # 2. Check for active execution runs (queued or running)
    active_runs_q = db.query(Run).filter(
        Run.experiment_id == experiment.id,
        Run.status.in_(["queued", "running"])
    )
    if rep:
        active_runs_q = active_runs_q.filter(Run.repetition_id == rep.id)
    active_runs = active_runs_q.count()
    if active_runs > 0 or (rep and rep.status in {"starting", "running"}) or (not rep and experiment.status in {"starting", "running"}):
        return False, "EXPERIMENT_STILL_ACTIVE", "Evaluation cannot start while experiment runs are still active. Wait until execution finishes or stop the experiment first."

    # 3. Check for saved runs
    saved_runs_q = db.query(Run).filter_by(experiment_id=experiment.id)
    if rep:
        saved_runs_q = saved_runs_q.filter(Run.repetition_id == rep.id)
    saved_runs = saved_runs_q.count()
    if saved_runs == 0:
        return False, "NO_SAVED_RUNS", "No saved runs found for this experiment. Runs must be executed before evaluation."

    # 4. Check dataset snapshot
    snapshot = db.get(DatasetSnapshot, experiment.dataset_snapshot_id)
    if not snapshot:
        return False, "SNAPSHOT_MISSING", "Experiment dataset snapshot is missing or unavailable."

    return True, None, None

def evaluate_experiment(
    db: Session,
    experiment: Experiment,
    force: bool = False,
    repetition_id: str | None = None,
    repetition_index: int | None = None,
) -> Evaluation:
    """Evaluates an experiment offline against its immutable dataset snapshot.
    Never calls the model provider or reruns the agent."""
    is_ready, err_code, err_msg = check_evaluation_readiness(
        db, experiment, repetition_id=repetition_id, repetition_index=repetition_index
    )
    if not is_ready and not (err_code == "EVALUATION_ALREADY_RUNNING" and not force):
        raise ValueError(err_msg)

    rep = _resolve_target_repetition(db, experiment, repetition_id, repetition_index)

    exist_q = (
        db.query(Evaluation)
        .filter_by(
            experiment_id=experiment.id,
            evaluation_schema_version=EVALUATION_SCHEMA_VERSION,
            metric_definition_version=METRIC_DEFINITION_VERSION,
            status="completed",
        )
    )
    if rep:
        exist_q = exist_q.filter(Evaluation.repetition_id == rep.id)
    existing = exist_q.order_by(Evaluation.created_at.desc()).first()
    if existing and not force:
        return existing

    snapshot = db.get(DatasetSnapshot, experiment.dataset_snapshot_id)
    if not snapshot:
        raise ValueError("experiment dataset snapshot is missing")

    fmt = Path(snapshot.storage_path).suffix.lstrip(".")
    records = {
        i - 1 if fmt == "jsonl" else i: record
        for i, record in _records(Path(snapshot.storage_path), fmt)
    }

    item = Evaluation(
        id=uid("eval"),
        experiment_id=experiment.id,
        repetition_id=rep.id if rep else None,
        repetition_index=rep.repetition_index if rep else 1,
        dataset_snapshot_id=snapshot.id,
        dataset_fingerprint=snapshot.fingerprint,
        evaluation_schema_version=EVALUATION_SCHEMA_VERSION,
        metric_definition_version=METRIC_DEFINITION_VERSION,
        status="running",
        expected_run_count=len(records),
    )
    db.add(item)
    db.flush()

    runs_q = db.query(Run).filter_by(experiment_id=experiment.id)
    if rep:
        runs_q = runs_q.filter(Run.repetition_id == rep.id)
    runs = runs_q.order_by(Run.record_index).all()
    if rep and not runs:
        runs = db.query(Run).filter_by(experiment_id=experiment.id).order_by(Run.record_index).all()
    result_rows = []

    for run in runs:
        record = records.get(run.record_index)
        detail = (
            evaluate_run(run, record, experiment.id)
            if isinstance(record, dict)
            else {
                "scenario_id": "unknown",
                "category": "unknown",
                "execution_status": run.status,
                "output_schema_valid": False,
                "task_completion": {"status": "unscored", "reason_codes": ["SNAPSHOT_RECORD_MISSING"], "assessment_method": "none"},
                "claim_assessments": [],
                "unsupported_action": {"present": None, "count": 0, "assessment_status": "unscored"},
                "recovery": {"status": "unscored", "reason": "SNAPSHOT_RECORD_MISSING"},
                "false_success": {"status": "not_assessable", "reason": "NO_RECORD"},
                "decision_signature": {},
                "review_required": True,
                "warnings": [],
                "exclusions": ["SNAPSHOT_RECORD_MISSING"],
            }
        )
        row = RunEvaluation(id=uid("reval"), evaluation_id=item.id, run_id=run.id, **detail)
        db.add(row)
        result_rows.append(row)

    db.flush()
    expected_scenarios = [
        (r.get("scenario_id", "unknown"), r.get("category", "unknown"))
        for r in records.values()
        if isinstance(r, dict)
    ]

    item.metrics = calculate_metrics(result_rows, expected_scenarios)
    completed = sum(r.status == "completed" for r in runs)
    failed = sum(r.status == "failed" for r in runs)
    missing = max(0, len(records) - len(runs))
    review = sum(r.review_required for r in result_rows)

    is_incomplete = bool(missing > 0 or failed > 0 or completed < len(records))

    item.manifest = {
        "experiment_id": experiment.id,
        "repetition_id": rep.id if rep else None,
        "repetition_index": rep.repetition_index if rep else 1,
        "evaluation_id": item.id,
        "dataset_snapshot_id": snapshot.id,
        "dataset_fingerprint": snapshot.fingerprint,
        "metric_definition_version": METRIC_DEFINITION_VERSION,
        "evaluation_schema_version": EVALUATION_SCHEMA_VERSION,
        "evaluated_run_ids": [r.run_id for r in result_rows],
        "expected_run_count": len(records),
        "completed_run_count": completed,
        "failed_run_count": failed,
        "missing_run_count": missing,
        "excluded_run_count": sum(bool(r.exclusions) for r in result_rows),
        "review_required_count": review,
        "evaluation_status": "INCOMPLETE" if is_incomplete else "COMPLETED",
        "coverage_percentage": round(completed / len(records) * 100, 2) if len(records) else 0.0,
    }
    item.status = "completed"
    item.completed_at = datetime.utcnow()
    if rep:
        rep.evaluation_id = item.id
    db.commit()
    db.refresh(item)
    return item
