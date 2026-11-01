from app.integrations.registry import RegisteredMockAdapter, HTTPAgentAdapter
from app.models.entities import AgentRegistration

def registration(adapter_type="mock", **values):
    return AgentRegistration(
        id="custom-test-agent", display_name="Custom Test", agent_type="custom_python" if adapter_type=="mock" else "external_http",
        adapter_type=adapter_type, version="1", status="ready", capabilities=[], **values,
    )

def test_registered_mock_enforces_input_schema_and_normalizes_result():
    adapter=RegisteredMockAdapter(registration(input_schema={"type":"object","required":["document"]}))
    assert adapter.validate_input({})
    result=adapter.run({"document":"news"}, None)
    assert result.run_status == "completed"
    assert result.normalized_output["agent"] == "custom-test-agent"

def test_http_agent_rejects_loopback_by_default():
    adapter=HTTPAgentAdapter(registration("http", adapter_config={"endpoint":"http://127.0.0.1:9999"}))
    errors=adapter.validate_configuration(adapter.item.adapter_config)
    assert any("loopback" in error for error in errors)
