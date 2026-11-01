import json
from app.integrations.financial_news import FinancialNewsAnalysisAgent
from app.services import providers, tavily

INPUT={"schema_version":"1.0","scenario_id":"NORMAL-001","ticker":"AAPL","company_name":"Apple Inc.","task":"Analyze supplied evidence.","retrieval_mode":"provided_evidence","search_query":None,"evidence":[{"evidence_id":"E1","type":"news","title":"Growth","content":"Revenue grew.","source_name":"Fixture","url":"https://example.test/e1"}]}
OUTPUT={"schema_version":"1.0","scenario_id":"NORMAL-001","ticker":"AAPL","sentiment":"positive","price_impact":"positive","recommendation":"BUY","confidence":0.7,"forecast_pct":None,"forecast_horizon":"unspecified","reasoning":[{"text":"Revenue grew.","evidence_ids":["E1","UNKNOWN"]}],"key_factors":[],"risk_factors":[],"missing_information":["Market expectations"],"source_ids_used":["E1"]}

def test_provider_call_uses_only_input_and_preserves_unknown_reference(monkeypatch):
    captured={}
    def generate(db, provider_id, messages, model, generation):
        captured.update(provider_id=provider_id,messages=messages,model=model,generation=generation)
        return {"choices":[{"message":{"content":json.dumps(OUTPUT)}}]}
    monkeypatch.setattr(providers,"generate",generate)
    result=FinancialNewsAnalysisAgent(object()).run(INPUT,configuration={"provider_id":"configured","model_override":"override","generation_settings":{"temperature":0}})
    assert result.run_status == "completed"
    assert result.normalized_output["forecast_pct"] is None
    assert result.metadata["validation_warnings"][0]["evidence_id"] == "UNKNOWN"
    prompt=captured["messages"][1]["content"]
    assert captured["provider_id"] == "configured" and captured["model"] == "override"
    assert "ground_truth" not in prompt and "Revenue grew" in prompt

def test_malformed_model_json_and_provider_errors_are_honest(monkeypatch):
    monkeypatch.setattr(providers,"generate",lambda *args: {"choices":[{"message":{"content":"not json"}}]})
    assert FinancialNewsAnalysisAgent(object()).run(INPUT,configuration={"provider_id":"p"}).error_code == "MODEL_OUTPUT_INVALID"
    monkeypatch.setattr(providers,"generate",lambda *args: (_ for _ in ()).throw(providers.ProviderError("PROVIDER_UNREACHABLE","unreachable")))
    assert FinancialNewsAnalysisAgent(object()).run(INPUT,configuration={"provider_id":"p"}).error_code == "PROVIDER_UNREACHABLE"

def test_provided_evidence_never_calls_tavily(monkeypatch):
    monkeypatch.setattr(tavily,"search",lambda query: (_ for _ in ()).throw(AssertionError("unexpected search")))
    monkeypatch.setattr(providers,"generate",lambda *args: {"choices":[{"message":{"content":json.dumps(OUTPUT)}}]})
    assert FinancialNewsAnalysisAgent(object()).run(INPUT,configuration={"provider_id":"p"}).run_status == "completed"

def test_invalid_input_and_mocked_live_retrieval(monkeypatch):
    assert FinancialNewsAnalysisAgent(object()).validate_input({"ticker":"AAPL"})
    live={**INPUT,"retrieval_mode":"tavily_live","evidence":[]}
    monkeypatch.setattr(tavily,"search",lambda query: [])
    monkeypatch.setattr(providers,"generate",lambda *args: {"choices":[{"message":{"content":json.dumps({**OUTPUT,"sentiment":"insufficient_evidence","price_impact":"uncertain","recommendation":"HOLD","confidence":0.1,"reasoning":[]})}}]})
    result=FinancialNewsAnalysisAgent(object()).run(live,configuration={"provider_id":"p"})
    assert result.run_status == "completed" and result.metadata["retrieval"]["performed"]
