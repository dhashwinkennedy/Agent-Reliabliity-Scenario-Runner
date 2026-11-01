import json
from types import SimpleNamespace
import pytest

from app.integrations.financial_news import (
    FinancialNewsEgalAgent,
    _directly_supported,
    _is_reasonable_inference,
    _contradicted_by_supplied_evidence,
    _validate_claims,
    _assess_sufficiency,
    _abstention_policy,
)
from app.schemas.financial_news import FinancialNewsInput, FinancialNewsOutput
from app.services import providers


def make_input(evidence_items, scenario_id="NORMAL-001"):
    return {
        "schema_version": "1.0",
        "scenario_id": scenario_id,
        "ticker": "ABC",
        "company_name": "ABC Corp",
        "task": "Analyze supplied evidence.",
        "retrieval_mode": "provided_evidence",
        "search_query": None,
        "evidence": evidence_items,
    }


def make_output(reasoning, recommendation="BUY", key_factors=None, risk_factors=None, missing_info=None, forecast_pct=None):
    return {
        "schema_version": "1.0",
        "scenario_id": "NORMAL-001",
        "ticker": "ABC",
        "sentiment": "positive" if recommendation == "BUY" else ("neutral" if recommendation == "HOLD" else "negative"),
        "price_impact": "positive" if recommendation == "BUY" else ("uncertain" if recommendation == "HOLD" else "negative"),
        "recommendation": recommendation,
        "confidence": 0.8 if recommendation != "ABSTAIN" else 0.0,
        "forecast_pct": forecast_pct,
        "forecast_horizon": "unspecified",
        "reasoning": [{"text": r, "evidence_ids": ["E1"]} for r in reasoning],
        "key_factors": [{"text": k, "evidence_ids": ["E1"]} for k in (key_factors or [])],
        "risk_factors": [{"text": rf, "evidence_ids": ["E1"]} for rf in (risk_factors or [])],
        "missing_information": missing_info or [],
        "source_ids_used": ["E1"],
    }


def completion(data):
    return {"choices": [{"message": {"content": json.dumps(data)}}]}


# 1. Well-supported normal scenario with paraphrased evidence: accepts without abstaining
def test_1_well_supported_normal_paraphrased_evidence_accepts_without_abstaining(monkeypatch):
    evidence = [{
        "evidence_id": "E1", "type": "news", "title": "Quarterly Earnings",
        "content": "ABC Motors reported quarterly revenue of ₹12,000 crore, up 10% year-over-year. Net profit increased 8% to ₹900 crore.",
        "source_name": "Fixture", "url": "https://example.test/e1",
    }]
    inp = make_input(evidence, scenario_id="NORMAL-001")
    # Paraphrased facts: "increased by 10% year-over-year to ₹12,000 crore"
    model_res = make_output(
        reasoning=["Quarterly revenue increased by 10% year-over-year to ₹12,000 crore."],
        key_factors=["Net profit increased by 8% to ₹900 crore."],
        recommendation="BUY",
    )
    monkeypatch.setattr(providers, "generate", lambda *args: completion(model_res))
    agent = FinancialNewsEgalAgent(object())
    result = agent.run(inp, configuration={"provider_id": "mock"})

    assert result.run_status == "completed"
    assert result.normalized_output["recommendation"] == "BUY"
    assert result.normalized_output["abstention"]["status"] == "not_abstained"
    assert result.normalized_output["audit"]["correction"]["executed"] is False


# 2. Normal scenario with minor peripheral uncertainty noted in risk factors: completes with appropriate recommendation
def test_2_normal_scenario_minor_peripheral_uncertainty_in_risk_factors(monkeypatch):
    evidence = [{
        "evidence_id": "E1", "type": "news", "title": "Product Launch",
        "content": "NovaTech launched its NovaEdge 5 laptop series with 120,000 pre-registrations. Initial reception was positive across major retailers.",
        "source_name": "Fixture", "url": "https://example.test/e2",
    }]
    inp = make_input(evidence, scenario_id="NORMAL-002")
    model_res = make_output(
        reasoning=["NovaTech received strong early consumer interest for its new NovaEdge series."],
        key_factors=["120,000 pre-registrations recorded for the NovaEdge series."],
        risk_factors=["No formal revenue guidance or sales targets were disclosed, leading to general market uncertainty around financial impact."],
        recommendation="BUY",
    )
    monkeypatch.setattr(providers, "generate", lambda *args: completion(model_res))
    agent = FinancialNewsEgalAgent(object())
    result = agent.run(inp, configuration={"provider_id": "mock"})

    assert result.run_status == "completed"
    assert result.normalized_output["recommendation"] == "BUY"
    assert result.normalized_output["abstention"]["status"] == "not_abstained"


# 3. Normal scenario with quantitative facts that match numbers in source text: accepted
def test_3_normal_scenario_quantitative_facts_matching_source_numbers_accepted(monkeypatch):
    evidence = [{
        "evidence_id": "E1", "type": "news", "title": "Delivery Figures",
        "content": "The company sold 142,000 vehicles during the quarter, compared with 129,000 a year earlier. Operating profit stood at ₹900 crore.",
        "source_name": "Fixture", "url": "https://example.test/e3",
    }]
    inp = make_input(evidence, scenario_id="NORMAL-001")
    model_res = make_output(
        reasoning=["Quarterly vehicle deliveries reached 142,000 units compared to 129,000 in the previous year."],
        key_factors=["Operating profit reached ₹900 crore."],
        recommendation="BUY",
    )
    monkeypatch.setattr(providers, "generate", lambda *args: completion(model_res))
    agent = FinancialNewsEgalAgent(object())
    result = agent.run(inp, configuration={"provider_id": "mock"})

    assert result.run_status == "completed"
    assert result.normalized_output["recommendation"] == "BUY"
    assert result.normalized_output["abstention"]["status"] == "not_abstained"


# 4. Ambiguous scenario with conflicting evidence: correctly identified, attempts correction or abstains if unresolved
def test_4_ambiguous_scenario_conflicting_evidence_unresolved_abstains(monkeypatch):
    evidence = [{
        "evidence_id": "E1", "type": "news", "title": "Market Report",
        "content": "Shares rose 4% following unconfirmed strategic rumors, while regulatory authorities announced an active audit.",
        "source_name": "Fixture", "url": "https://example.test/e4",
    }]
    inp = make_input(evidence, scenario_id="AMBIGUOUS-001")
    # First call: ungrounded directional BUY claiming massive guaranteed return
    resp1 = make_output(
        reasoning=["Company is guaranteed to double shareholder wealth."],
        recommendation="BUY",
    )
    # Second call (correction): still asserts ungrounded claim and aggressive BUY
    resp2 = make_output(
        reasoning=["Company will definitely generate enormous 100% returns."],
        recommendation="BUY",
    )
    responses = iter([completion(resp1), completion(resp2)])
    calls = []
    monkeypatch.setattr(providers, "generate", lambda *args: (calls.append(args), next(responses))[1])

    agent = FinancialNewsEgalAgent(object())
    result = agent.run(inp, configuration={"provider_id": "mock"})

    assert result.run_status == "completed"
    assert len(calls) == 2
    assert result.normalized_output["recommendation"] == "ABSTAIN"
    assert result.normalized_output["abstention"]["status"] == "abstained"
    assert "MATERIAL_UNSUPPORTED_CLAIMS" in result.normalized_output["abstention"]["reason_codes"] or \
           "RECOMMENDATION_NOT_ADEQUATELY_SUPPORTED" in result.normalized_output["abstention"]["reason_codes"]


# 5. Ambiguous scenario where HOLD is well-grounded by balanced evidence: completes with HOLD, does NOT abstain
def test_5_ambiguous_scenario_hold_well_grounded_by_balanced_evidence_no_abstain(monkeypatch):
    evidence = [{
        "evidence_id": "E1", "type": "news", "title": "Quarterly Mixed Results",
        "content": "ABC Motors reported quarterly revenue of ₹12,000 crore, up 10% year-over-year. However, operating expenses rose 15%, and management gave no full-year guidance.",
        "source_name": "Fixture", "url": "https://example.test/e5",
    }]
    inp = make_input(evidence, scenario_id="AMBIGUOUS-002")
    model_res = make_output(
        reasoning=["Revenue grew 10% to ₹12,000 crore, but operating expenses increased 15%."],
        key_factors=["Quarterly revenue up 10% year-over-year."],
        risk_factors=["Operating expenses rose 15%, compressing margins."],
        missing_info=["Full-year earnings guidance was not provided by management."],
        recommendation="HOLD",
    )
    monkeypatch.setattr(providers, "generate", lambda *args: completion(model_res))
    agent = FinancialNewsEgalAgent(object())
    result = agent.run(inp, configuration={"provider_id": "mock"})

    assert result.run_status == "completed"
    assert result.normalized_output["recommendation"] == "HOLD"
    assert result.normalized_output["abstention"]["status"] == "not_abstained"
    assert result.normalized_output["audit"]["correction"]["executed"] is False


# 6. Genuine failure scenario (complete contradiction): rejected, corrected or abstained
def test_6_genuine_failure_complete_contradiction_rejected_and_abstains(monkeypatch):
    evidence = [{
        "evidence_id": "E1", "type": "news", "title": "Severe Losses",
        "content": "ABC Motors reported a massive net loss of ₹900 crore as sales declined 25%.",
        "source_name": "Fixture", "url": "https://example.test/e6",
    }]
    inp = make_input(evidence, scenario_id="FAILURE-001")
    # Model hallucinated net profit and sales grew
    hallucination_1 = make_output(
        reasoning=["ABC Motors reported net profit of ₹900 crore as sales grew 25%."],
        recommendation="BUY",
    )
    hallucination_2 = make_output(
        reasoning=["ABC Motors experienced net profit increase across key segments."],
        recommendation="BUY",
    )
    responses = iter([completion(hallucination_1), completion(hallucination_2)])
    calls = []
    monkeypatch.setattr(providers, "generate", lambda *args: (calls.append(args), next(responses))[1])

    agent = FinancialNewsEgalAgent(object())
    result = agent.run(inp, configuration={"provider_id": "mock"})

    assert result.run_status == "completed"
    assert len(calls) == 2
    assert result.normalized_output["recommendation"] == "ABSTAIN"
    assert result.normalized_output["abstention"]["status"] == "abstained"
    assert "MATERIAL_CONTRADICTIONS" in result.normalized_output["abstention"]["reason_codes"] or \
           "RECOMMENDATION_NOT_ADEQUATELY_SUPPORTED" in result.normalized_output["abstention"]["reason_codes"]


# 7. Genuine failure scenario (fabricated numbers not in source): correctly flagged as unsupported, abstains
def test_7_genuine_failure_fabricated_numbers_flagged_and_abstains(monkeypatch):
    evidence = [{
        "evidence_id": "E1", "type": "news", "title": "Small Expansion",
        "content": "ABC Motors opened 3 new distribution centers in the region.",
        "source_name": "Fixture", "url": "https://example.test/e7",
    }]
    inp = make_input(evidence, scenario_id="FAILURE-002")
    # Model introduces fabricated financial metrics not in source (₹50,000 crore revenue, 75% growth)
    resp1 = make_output(
        reasoning=["ABC Motors achieved ₹50,000 crore in sales with 75% growth."],
        recommendation="BUY",
    )
    resp2 = make_output(
        reasoning=["Sales jumped by 60% to ₹40,000 crore."],
        recommendation="BUY",
    )
    responses = iter([completion(resp1), completion(resp2)])
    calls = []
    monkeypatch.setattr(providers, "generate", lambda *args: (calls.append(args), next(responses))[1])

    agent = FinancialNewsEgalAgent(object())
    result = agent.run(inp, configuration={"provider_id": "mock"})

    assert result.run_status == "completed"
    assert len(calls) == 2
    assert result.normalized_output["recommendation"] == "ABSTAIN"
    assert result.normalized_output["abstention"]["status"] == "abstained"
    assert "MATERIAL_UNSUPPORTED_CLAIMS" in result.normalized_output["abstention"]["reason_codes"]


# 8. Unsupported claim correction: single correction attempted; if fixed, completes successfully
def test_8_unsupported_claim_correction_fixed_completes_successfully(monkeypatch):
    evidence = [{
        "evidence_id": "E1", "type": "news", "title": "Earnings Report",
        "content": "Revenue grew 10% in the reported quarter.",
        "source_name": "Fixture", "url": "https://example.test/e8",
    }]
    inp = make_input(evidence)
    # Attempt 1: unsupported hallucinated claim
    unsupported = make_output(
        reasoning=["Company plans to double revenue next year through massive overseas buyout."],
        recommendation="BUY",
    )
    # Attempt 2 (correction): corrected to grounded factual claim
    grounded = make_output(
        reasoning=["Revenue grew 10% in the reported quarter."],
        recommendation="BUY",
    )
    responses = iter([completion(unsupported), completion(grounded)])
    calls = []
    monkeypatch.setattr(providers, "generate", lambda *args: (calls.append(args), next(responses))[1])

    agent = FinancialNewsEgalAgent(object())
    result = agent.run(inp, configuration={"provider_id": "mock"})

    assert result.run_status == "completed"
    assert len(calls) == 2
    assert result.normalized_output["audit"]["correction"]["executed"] is True
    assert result.normalized_output["recommendation"] == "BUY"
    assert result.normalized_output["abstention"]["status"] == "not_abstained"


# 9. Unsupported claim correction: single correction attempted; if still unsupported, abstains
def test_9_unsupported_claim_correction_still_unsupported_abstains(monkeypatch):
    evidence = [{
        "evidence_id": "E1", "type": "news", "title": "Earnings Report",
        "content": "Revenue grew 10% in the reported quarter.",
        "source_name": "Fixture", "url": "https://example.test/e9",
    }]
    inp = make_input(evidence)
    # Attempt 1: unsupported
    resp1 = make_output(
        reasoning=["Company will double revenue next year."],
        recommendation="BUY",
    )
    # Attempt 2: still unsupported
    resp2 = make_output(
        reasoning=["Company will triple revenue next year."],
        recommendation="BUY",
    )
    responses = iter([completion(resp1), completion(resp2)])
    calls = []
    monkeypatch.setattr(providers, "generate", lambda *args: (calls.append(args), next(responses))[1])

    agent = FinancialNewsEgalAgent(object())
    result = agent.run(inp, configuration={"provider_id": "mock"})

    assert result.run_status == "completed"
    assert len(calls) == 2  # At most 1 correction attempt (no loops)
    assert result.normalized_output["audit"]["correction"]["executed"] is True
    assert result.normalized_output["recommendation"] == "ABSTAIN"
    assert result.normalized_output["abstention"]["status"] == "abstained"


# 10. Direct evidence vs inference: direct evidence requires source grounding; inference allowed only when explicitly marked and logically consistent
def test_10_direct_evidence_vs_inference_distinction():
    evidence = [SimpleNamespace(
        evidence_id="E1",
        title="Quarterly earnings",
        content="ABC Motors reported quarterly revenue of ₹12,000 crore, up 10% year-over-year. Operating efficiency improved during the period.",
    )]

    # Case A: Factual claim without qualification that is not in source -> unsupported
    unsupported_fact = "ABC Motors expanded into 20 new foreign countries."
    assert not _directly_supported(unsupported_fact, evidence)
    assert not _is_reasonable_inference(unsupported_fact, evidence)

    # Case B: Qualified inference logically connected to source -> reasonable inference
    valid_inference = "Improved operating efficiency suggests potential margin resilience in future quarters."
    assert _is_reasonable_inference(valid_inference, evidence)

    # Case C: Qualified inference that introduces fabricated numbers -> rejected
    inference_fake_num = "Improved operating efficiency suggests profit margins could reach 45% next year."
    assert not _is_reasonable_inference(inference_fake_num, evidence)

    # Case D: Direct factual claim grounded in source -> supported fact
    grounded_fact = "Quarterly revenue was ₹12,000 crore, up 10% year-over-year."
    assert _directly_supported(grounded_fact, evidence)


# 11. Distinction between HOLD and ABSTAIN: HOLD represents an investment posture supported by mixed/neutral evidence; ABSTAIN represents insufficient evidence or unfixable validation failure
def test_11_distinction_between_hold_and_abstain(monkeypatch):
    evidence = [{
        "evidence_id": "E1", "type": "news", "title": "Mixed Drivers",
        "content": "Revenue grew 10% to ₹12,000 crore, while costs rose 14% and management withheld full-year outlook.",
        "source_name": "Fixture", "url": "https://example.test/e11",
    }]
    # Subtest A: HOLD as an active, well-grounded cautious investment posture
    hold_out = make_output(
        reasoning=["Revenue increased 10% to ₹12,000 crore, but costs rose 14%."],
        key_factors=["Quarterly revenue rose 10% to ₹12,000 crore."],
        risk_factors=["Cost increases of 14% create margin uncertainty."],
        missing_info=["Full-year earnings outlook withheld."],
        recommendation="HOLD",
    )
    monkeypatch.setattr(providers, "generate", lambda *args: completion(hold_out))
    agent = FinancialNewsEgalAgent(object())
    hold_result = agent.run(make_input(evidence), configuration={"provider_id": "mock"})

    assert hold_result.normalized_output["recommendation"] == "HOLD"
    assert hold_result.normalized_output["confidence"] > 0.0
    assert hold_result.normalized_output["abstention"]["status"] == "not_abstained"
    assert hold_result.normalized_output["abstention"]["reason_codes"] == []

    # Subtest B: ABSTAIN when evidence is completely empty
    empty_input = make_input([], scenario_id="NORMAL-001")
    empty_out = make_output(
        reasoning=["Cannot analyze without data."],
        recommendation="HOLD",
    )
    empty_out["reasoning"][0]["evidence_ids"] = []
    empty_out["source_ids_used"] = []
    monkeypatch.setattr(providers, "generate", lambda *args: completion(empty_out))
    abstain_result = agent.run(empty_input, configuration={"provider_id": "mock"})

    assert abstain_result.normalized_output["recommendation"] == "ABSTAIN"
    assert abstain_result.normalized_output["confidence"] == 0.0
    assert abstain_result.normalized_output["sentiment"] == "insufficient_evidence"
    assert abstain_result.normalized_output["price_impact"] == "uncertain"
    assert abstain_result.normalized_output["abstention"]["status"] == "abstained"
    assert "CRITICAL_MISSING_INFORMATION" in abstain_result.normalized_output["abstention"]["reason_codes"]
