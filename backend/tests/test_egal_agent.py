import json

from app.integrations.financial_news import FinancialNewsEgalAgent
from app.services import providers, tavily


INPUT = {
    "schema_version": "1.0", "scenario_id": "NORMAL-001", "ticker": "AAPL",
    "company_name": "Apple Inc.", "task": "Analyze supplied evidence.",
    "retrieval_mode": "tavily_live", "search_query": "do not use this", "evidence": [{
        "evidence_id": "E1", "type": "news", "title": "Results",
        "content": "Revenue grew 10% in the reported quarter.", "source_name": "Fixture", "url": "https://example.test/e1",
    }],
}


def output(reasoning="Revenue grew 10% in the reported quarter.", recommendation="BUY"):
    return {
        "schema_version": "1.0", "scenario_id": "NORMAL-001", "ticker": "AAPL",
        "sentiment": "positive", "price_impact": "positive", "recommendation": recommendation,
        "confidence": 0.6, "forecast_pct": None, "forecast_horizon": "unspecified",
        "reasoning": [{"text": reasoning, "evidence_ids": ["E1"]}],
        "key_factors": [], "risk_factors": [], "missing_information": [], "source_ids_used": ["E1"],
    }


def completion(value):
    return {"choices": [{"message": {"content": json.dumps(value)}}]}


def test_supported_case_is_final_without_correction_and_never_retrieves(monkeypatch):
    calls, prompts = [], []
    def generate(*args):
        calls.append(args); prompts.append(args[2][1]["content"])
        return completion(output())
    monkeypatch.setattr(providers, "generate", generate)
    monkeypatch.setattr(tavily, "search", lambda _: (_ for _ in ()).throw(AssertionError("EGAL must not retrieve")))
    result = FinancialNewsEgalAgent(object()).run(INPUT, configuration={"provider_id": "p"})
    assert result.run_status == "completed"
    assert len(calls) == 1
    assert result.normalized_output["recommendation"] == "BUY"
    assert result.normalized_output["audit"]["correction"]["executed"] is False
    assert all("ground_truth" not in prompt for prompt in prompts)


def test_unsupported_claim_gets_exactly_one_correction_attempt(monkeypatch):
    responses = iter([completion(output("The company will double revenue next year.")), completion(output())])
    calls = []
    monkeypatch.setattr(providers, "generate", lambda *args: (calls.append(args), next(responses))[1])
    result = FinancialNewsEgalAgent(object()).run(INPUT, configuration={"provider_id": "p"})
    assert result.run_status == "completed" and len(calls) == 2
    assert result.normalized_output["recommendation"] == "BUY"
    assert result.normalized_output["audit"]["correction"]["executed"] is True
    assert result.raw_output["correction_completion"] is not None


def test_residual_material_issue_abstains_without_a_loop(monkeypatch):
    responses = iter([completion(output("The company will double revenue next year.")), completion(output("The company will triple revenue next year."))])
    calls = []
    monkeypatch.setattr(providers, "generate", lambda *args: (calls.append(args), next(responses))[1])
    result = FinancialNewsEgalAgent(object()).run(INPUT, configuration={"provider_id": "p"})
    assert result.run_status == "completed" and len(calls) == 2
    assert result.normalized_output["recommendation"] == "ABSTAIN"
    assert result.normalized_output["abstention"]["status"] == "abstained"


def test_empty_evidence_abstains_without_correction(monkeypatch):
    empty = {**INPUT, "evidence": []}
    value = output("An unsupported view.")
    value["reasoning"][0]["evidence_ids"] = []
    calls = []
    monkeypatch.setattr(providers, "generate", lambda *args: (calls.append(args), completion(value))[1])
    result = FinancialNewsEgalAgent(object()).run(empty, configuration={"provider_id": "p"})
    assert result.run_status == "completed" and len(calls) == 1
    assert result.normalized_output["recommendation"] == "ABSTAIN"
    assert result.normalized_output["audit"]["correction"]["executed"] is False


def test_provider_failure_is_failed_not_abstained(monkeypatch):
    monkeypatch.setattr(providers, "generate", lambda *args: (_ for _ in ()).throw(providers.ProviderError("PROVIDER_UNREACHABLE", "offline")))
    result = FinancialNewsEgalAgent(object()).run(INPUT, configuration={"provider_id": "p"})
    assert result.run_status == "failed"
    assert result.error_code == "PROVIDER_UNREACHABLE"
    assert result.normalized_output is None


def test_audit_has_stable_versioned_structure(monkeypatch):
    monkeypatch.setattr(providers, "generate", lambda *args: completion(output()))
    audit = FinancialNewsEgalAgent(object()).run(INPUT, configuration={"provider_id": "p"}).normalized_output["audit"]
    assert audit["policy_version"] == "egal-evidence-policy-v2"
    assert {"original_output", "initial_claim_validation", "initial_evidence_sufficiency", "correction", "final_claim_validation", "final_evidence_sufficiency", "final_decision", "stage_timings_ms"} <= set(audit)
    assert audit["provider"]["call_count"] == 1
