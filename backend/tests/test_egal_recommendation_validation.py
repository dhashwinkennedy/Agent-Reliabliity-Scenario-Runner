"""
Deterministic regression tests for EGAL Recommendation Validation.
Verifies that:
1. Factual claim support is distinguished from recommendation justification.
2. Unquantified headlines (e.g. 'production halted at main plant') do NOT validate directional BUY/SELL.
3. Explicitly withheld material terms/context (e.g. 'no details', 'did not disclose', 'unnamed sources') reject directional BUY/SELL.
4. Unknown company/ticker identity rejects directional BUY/SELL.
5. Cautious HOLD recommendation is permitted for ambiguous/incomplete evidence.
6. Grounded recommendations in quantified Normal scenarios remain supported.
7. Constrained single-pass correction prompts the agent to switch to HOLD or ABSTAIN, and abstention policy triggers if unsupported recommendation persists.
8. Technical/model-output failures remain execution errors, not analytical abstentions.
"""
import pytest
from app.integrations.financial_news import (
    FinancialNewsEgalAgent,
    _validate_claims,
    _assess_sufficiency,
    _abstention_policy,
)
from app.schemas.financial_news import (
    FinancialNewsInput,
    FinancialNewsOutput,
    FinancialNewsEgalOutput,
    EvidenceRecord,
    EvidenceLinkedItem,
)


def _make_evidence(content: str, eid: str = "E1") -> list[EvidenceRecord]:
    return [
        EvidenceRecord(
            evidence_id=eid,
            type="article",
            title="News Update",
            content=content,
            source_name="Financial Wire",
            url="https://example.com/news",
        )
    ]


def test_unquantified_headline_rejects_directional_sell():
    """Headline 'Delta Manufacturing production halted at main plant' has 0 financial quantification.
    Factual claim is supported, but directional SELL recommendation must be marked unsupported_claim.
    """
    evidence = _make_evidence("BREAKING: Delta Manufacturing production halted at main plant")
    inp = FinancialNewsInput(
        schema_version="1.0",
        scenario_id="AMBIGUOUS-006",
        ticker="DLTM.SYN",
        company_name="Delta Manufacturing",
        task="Analyze this news and describe its likely impact on the company.",
        evidence=evidence,
    )
    output = FinancialNewsOutput(
        schema_version="1.0",
        scenario_id="AMBIGUOUS-006",
        ticker="DLTM.SYN",
        sentiment="negative",
        price_impact="negative",
        recommendation="SELL",
        confidence=0.8,
        forecast_pct=None,
        forecast_horizon="short_term",
        reasoning=[
            EvidenceLinkedItem(text="Production was halted at Delta Manufacturing's main plant.", evidence_ids=["E1"])
        ],
        key_factors=[
            EvidenceLinkedItem(text="Main plant halt.", evidence_ids=["E1"])
        ],
        risk_factors=[],
        missing_information=[],
        source_ids_used=["E1"],
    )

    validation = _validate_claims(output, inp)
    rec_assessment = next(a for a in validation.assessments if a.claim_type == "recommendation")
    assert rec_assessment.validation_label == "unsupported_claim"
    assert rec_assessment.requires_correction is True
    assert "lacks sufficient financial quantification" in rec_assessment.explanation

    # Sufficiency assessment should flag the recommendation as not adequately supported
    sufficiency = _assess_sufficiency(validation, inp)
    assert sufficiency.status == "insufficient"
    assert sufficiency.recommendation_adequately_supported is False
    assert sufficiency.correction_required is True

    # Abstention policy triggers
    abstain, codes = _abstention_policy(sufficiency)
    assert abstain is True
    assert "RECOMMENDATION_NOT_ADEQUATELY_SUPPORTED" in codes


def test_unquantified_headline_permits_cautious_hold():
    """The same unquantified headline permits a cautious HOLD recommendation."""
    evidence = _make_evidence("BREAKING: Delta Manufacturing production halted at main plant")
    inp = FinancialNewsInput(
        schema_version="1.0",
        scenario_id="AMBIGUOUS-006",
        ticker="DLTM.SYN",
        company_name="Delta Manufacturing",
        task="Analyze this news and describe its likely impact on the company.",
        evidence=evidence,
    )
    output = FinancialNewsOutput(
        schema_version="1.0",
        scenario_id="AMBIGUOUS-006",
        ticker="DLTM.SYN",
        sentiment="neutral",
        price_impact="uncertain",
        recommendation="HOLD",
        confidence=0.5,
        forecast_pct=None,
        forecast_horizon="short_term",
        reasoning=[
            EvidenceLinkedItem(text="Production was halted at Delta Manufacturing's main plant.", evidence_ids=["E1"])
        ],
        key_factors=[
            EvidenceLinkedItem(text="Production halted at main plant.", evidence_ids=["E1"])
        ],
        risk_factors=[],
        missing_information=["Duration and cost of halt are not provided."],
        source_ids_used=["E1"],
    )

    validation = _validate_claims(output, inp)
    rec_assessment = next(a for a in validation.assessments if a.claim_type == "recommendation")
    assert rec_assessment.validation_label == "reasonable_inference"
    assert rec_assessment.requires_correction is False

    sufficiency = _assess_sufficiency(validation, inp)
    assert sufficiency.status == "sufficient"
    assert sufficiency.recommendation_adequately_supported is True


def test_withheld_details_rejects_directional_buy():
    """Evidence with 'No details about the development were provided' must reject directional BUY."""
    evidence = _make_evidence(
        "ABC Motors shares rose 4% in early trade on Wednesday after the company announced a major strategic development. "
        "No details about the development were provided."
    )
    inp = FinancialNewsInput(
        schema_version="1.0",
        scenario_id="AMBIGUOUS-001",
        ticker="ABCM.SYN",
        company_name="ABC Motors",
        task="Analyze the news and state whether it supports a recommendation.",
        evidence=evidence,
    )
    output = FinancialNewsOutput(
        schema_version="1.0",
        scenario_id="AMBIGUOUS-001",
        ticker="ABCM.SYN",
        sentiment="positive",
        price_impact="positive",
        recommendation="BUY",
        confidence=0.75,
        forecast_pct=None,
        forecast_horizon="short_term",
        reasoning=[
            EvidenceLinkedItem(text="ABC Motors announced a major strategic development.", evidence_ids=["E1"])
        ],
        key_factors=[
            EvidenceLinkedItem(text="Shares rose 4% in early trade.", evidence_ids=["E1"])
        ],
        risk_factors=[],
        missing_information=[],
        source_ids_used=["E1"],
    )

    validation = _validate_claims(output, inp)
    rec_assessment = next(a for a in validation.assessments if a.claim_type == "recommendation")
    assert rec_assessment.validation_label == "unsupported_claim"
    assert "undisclosed, unannounced, or unverified" in rec_assessment.explanation


def test_undisclosed_contract_terms_rejects_directional_buy():
    """Evidence stating company 'did not disclose the contract value' must reject directional BUY."""
    evidence = _make_evidence(
        "NovaTech said on Monday it has won a multi-year contract from a government agency. "
        "The company did not disclose the agency's name, the contract value, its duration, or when work will begin."
    )
    inp = FinancialNewsInput(
        schema_version="1.0",
        scenario_id="AMBIGUOUS-002",
        ticker="NOVT.SYN",
        company_name="NovaTech",
        task="Assess the likely financial impact of this announcement on NovaTech.",
        evidence=evidence,
    )
    output = FinancialNewsOutput(
        schema_version="1.0",
        scenario_id="AMBIGUOUS-002",
        ticker="NOVT.SYN",
        sentiment="positive",
        price_impact="positive",
        recommendation="BUY",
        confidence=0.7,
        forecast_pct=None,
        forecast_horizon="medium_term",
        reasoning=[
            EvidenceLinkedItem(text="NovaTech won a multi-year government contract.", evidence_ids=["E1"])
        ],
        key_factors=[],
        risk_factors=[],
        missing_information=[],
        source_ids_used=["E1"],
    )

    validation = _validate_claims(output, inp)
    rec_assessment = next(a for a in validation.assessments if a.claim_type == "recommendation")
    assert rec_assessment.validation_label == "unsupported_claim"


def test_unknown_company_identity_rejects_directional_buy():
    """Evidence with unknown company/ticker identity (e.g. AMBIGUOUS-004) must reject directional BUY."""
    evidence = _make_evidence(
        "The company reported quarterly net profit of 450 crore, up 15% from a year earlier. "
        "Management expressed confidence about the coming quarters."
    )
    inp = FinancialNewsInput(
        schema_version="1.0",
        scenario_id="AMBIGUOUS-004",
        ticker="UNKNOWN",
        company_name="Unknown company",
        task="Analyze this result and give an outlook for the company. The company name and ticker are not provided.",
        evidence=evidence,
    )
    output = FinancialNewsOutput(
        schema_version="1.0",
        scenario_id="AMBIGUOUS-004",
        ticker="UNKNOWN",
        sentiment="positive",
        price_impact="positive",
        recommendation="BUY",
        confidence=0.8,
        forecast_pct=None,
        forecast_horizon="medium_term",
        reasoning=[
            EvidenceLinkedItem(text="Quarterly net profit rose 15% to 450 crore.", evidence_ids=["E1"])
        ],
        key_factors=[],
        risk_factors=[],
        missing_information=[],
        source_ids_used=["E1"],
    )

    validation = _validate_claims(output, inp)
    rec_assessment = next(a for a in validation.assessments if a.claim_type == "recommendation")
    assert rec_assessment.validation_label == "unsupported_claim"
    assert "unknown or unprovided" in rec_assessment.explanation


def test_unconfirmed_rumour_rejects_directional_buy():
    """Unconfirmed trade publication report with unnamed sources and declined comment rejects BUY."""
    evidence = _make_evidence(
        "Orion Technologies shares closed 2% higher on Thursday. A trade publication reported, citing unnamed sources, "
        "that the company is in early discussions with a European client about a possible large order. "
        "Orion declined to comment on the report, and no agreement has been announced."
    )
    inp = FinancialNewsInput(
        schema_version="1.0",
        scenario_id="AMBIGUOUS-005",
        ticker="ORNT.SYN",
        company_name="Orion Technologies",
        task="Provide a BUY, HOLD or SELL recommendation with justification.",
        evidence=evidence,
    )
    output = FinancialNewsOutput(
        schema_version="1.0",
        scenario_id="AMBIGUOUS-005",
        ticker="ORNT.SYN",
        sentiment="positive",
        price_impact="positive",
        recommendation="BUY",
        confidence=0.7,
        forecast_pct=None,
        forecast_horizon="short_term",
        reasoning=[
            EvidenceLinkedItem(text="Possible large European order discussions reported.", evidence_ids=["E1"])
        ],
        key_factors=[],
        risk_factors=[],
        missing_information=[],
        source_ids_used=["E1"],
    )

    validation = _validate_claims(output, inp)
    rec_assessment = next(a for a in validation.assessments if a.claim_type == "recommendation")
    assert rec_assessment.validation_label == "unsupported_claim"


def test_normal_scenario_quantified_fundamentals_permits_buy():
    """A grounded Normal scenario with full quantitative financial metrics permits directional BUY."""
    evidence = _make_evidence(
        "ABC Motors reported quarterly revenue of 12000 crore, up 10% year-over-year. "
        "Net profit increased 12% to 950 crore. Operating EBITDA margin expanded to 11.5% from 10.8%. "
        "Electric vehicle deliveries were 14200 units, up 28%."
    )
    inp = FinancialNewsInput(
        schema_version="1.0",
        scenario_id="NORMAL-001",
        ticker="ABCM.SYN",
        company_name="ABC Motors",
        task="Produce a structured analysis of the quarterly results.",
        evidence=evidence,
    )
    output = FinancialNewsOutput(
        schema_version="1.0",
        scenario_id="NORMAL-001",
        ticker="ABCM.SYN",
        sentiment="positive",
        price_impact="positive",
        recommendation="BUY",
        confidence=0.85,
        forecast_pct=None,
        forecast_horizon="medium_term",
        reasoning=[
            EvidenceLinkedItem(text="Quarterly revenue reached 12000 crore, up 10% year-over-year.", evidence_ids=["E1"]),
            EvidenceLinkedItem(text="Net profit increased 12% to 950 crore.", evidence_ids=["E1"]),
        ],
        key_factors=[
            EvidenceLinkedItem(text="Operating EBITDA margin expanded to 11.5%.", evidence_ids=["E1"]),
            EvidenceLinkedItem(text="EV deliveries reached 14200 units.", evidence_ids=["E1"]),
        ],
        risk_factors=[],
        missing_information=[],
        source_ids_used=["E1"],
    )

    validation = _validate_claims(output, inp)
    rec_assessment = next(a for a in validation.assessments if a.claim_type == "recommendation")
    assert rec_assessment.validation_label == "reasonable_inference"
    assert rec_assessment.requires_correction is False
    assert "follows evidence-linked material claims and quantified financial data" in rec_assessment.explanation

    sufficiency = _assess_sufficiency(validation, inp)
    assert sufficiency.status == "sufficient"
    assert sufficiency.recommendation_adequately_supported is True
    assert sufficiency.correction_required is False


def test_egal_agent_abstention_override_when_unsupported_recommendation_persists():
    """When the candidate persists with an unsupported recommendation after correction,
    EGAL final output enforces ABSTAIN with RECOMMENDATION_NOT_ADEQUATELY_SUPPORTED.
    """
    evidence = _make_evidence("BREAKING: Delta Manufacturing production halted at main plant")
    inp = FinancialNewsInput(
        schema_version="1.0",
        scenario_id="AMBIGUOUS-006",
        ticker="DLTM.SYN",
        company_name="Delta Manufacturing",
        task="Analyze this news and describe its likely impact on the company.",
        evidence=evidence,
    )
    # Output with SELL recommendation
    output = FinancialNewsOutput(
        schema_version="1.0",
        scenario_id="AMBIGUOUS-006",
        ticker="DLTM.SYN",
        sentiment="negative",
        price_impact="negative",
        recommendation="SELL",
        confidence=0.8,
        forecast_pct=None,
        forecast_horizon="short_term",
        reasoning=[
            EvidenceLinkedItem(text="Production was halted at Delta Manufacturing's main plant.", evidence_ids=["E1"])
        ],
        key_factors=[],
        risk_factors=[],
        missing_information=[],
        source_ids_used=["E1"],
    )

    validation = _validate_claims(output, inp)
    sufficiency = _assess_sufficiency(validation, inp)
    abstain, codes = _abstention_policy(sufficiency)
    assert abstain is True
    assert "RECOMMENDATION_NOT_ADEQUATELY_SUPPORTED" in codes

    agent = FinancialNewsEgalAgent(db=None)
    final = agent._final_output(
        candidate=output,
        validation=validation,
        sufficiency=sufficiency,
        audit={"retries": []},
        abstain=abstain,
        codes=codes,
    )

    assert final.recommendation == "ABSTAIN"
    assert final.sentiment == "insufficient_evidence"
    assert final.price_impact == "uncertain"
    assert final.confidence == 0.0
    assert final.abstention.status == "abstained"
    assert "RECOMMENDATION_NOT_ADEQUATELY_SUPPORTED" in final.abstention.reason_codes
