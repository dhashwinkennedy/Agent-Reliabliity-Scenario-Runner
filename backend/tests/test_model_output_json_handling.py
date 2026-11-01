"""Regression tests for model output JSON extraction, code fence handling, and bounded retry behavior."""
import json
import pytest
from unittest.mock import MagicMock, patch

from app.integrations.financial_news import (
    FinancialNewsAnalysisAgent,
    FinancialNewsEgalAgent,
    ModelOutputInvalidError,
    _extract_json_text,
    _json,
    _call_and_parse_with_retry,
)
from app.schemas.financial_news import FinancialNewsInput, FinancialNewsOutput, FinancialNewsEgalOutput


VALID_FINANCIAL_OUTPUT = {
    "schema_version": "1.0",
    "scenario_id": "normal-001",
    "ticker": "AAPL",
    "sentiment": "positive",
    "price_impact": "positive",
    "recommendation": "BUY",
    "confidence": 0.8,
    "forecast_pct": 5.0,
    "forecast_horizon": "short_term",
    "reasoning": [{"text": "Revenue grew 10%", "evidence_ids": ["ev_1"]}],
    "key_factors": [{"text": "Strong iPhone sales", "evidence_ids": ["ev_1"]}],
    "risk_factors": [{"text": "Supply constraints", "evidence_ids": ["ev_1"]}],
    "missing_information": [],
    "source_ids_used": ["ev_1"],
}

SAMPLE_INPUT_PAYLOAD = {
    "schema_version": "1.0",
    "scenario_id": "normal-001",
    "ticker": "AAPL",
    "company_name": "Apple Inc.",
    "task": "Analyze earnings",
    "retrieval_mode": "provided_evidence",
    "evidence": [
        {
            "evidence_id": "ev_1",
            "type": "news",
            "title": "Apple Q3 Earnings",
            "content": "Revenue grew 10% driven by strong iPhone sales amid supply constraints.",
            "source_name": "Reuters",
            "url": "https://example.com/aapl",
        }
    ],
}


# ==============================================================================
# Test 1 — Valid JSON
# ==============================================================================
def test_valid_json_parsing():
    raw_json = json.dumps(VALID_FINANCIAL_OUTPUT)
    parsed = _json(raw_json)
    assert parsed["recommendation"] == "BUY"
    assert parsed["confidence"] == 0.8
    validated = FinancialNewsOutput.model_validate(parsed)
    assert validated.scenario_id == "normal-001"


# ==============================================================================
# Test 2 — JSON code fence handling
# ==============================================================================
def test_json_code_fence_extraction():
    # 2a: Standard ```json ... ```
    raw_with_fence = f"```json\n{json.dumps(VALID_FINANCIAL_OUTPUT, indent=2)}\n```"
    parsed_fence = _json(raw_with_fence)
    assert parsed_fence["ticker"] == "AAPL"

    # 2b: Code fence with preamble and postamble text
    raw_with_text = f"Here is the requested financial analysis:\n```json\n{json.dumps(VALID_FINANCIAL_OUTPUT)}\n```\nHope this helps!"
    parsed_surrounded = _json(raw_with_text)
    assert parsed_surrounded["sentiment"] == "positive"

    # 2c: Plain code fence without 'json' tag
    raw_plain_fence = f"```\n{json.dumps(VALID_FINANCIAL_OUTPUT)}\n```"
    parsed_plain = _json(raw_plain_fence)
    assert parsed_plain["recommendation"] == "BUY"


# ==============================================================================
# Test 3 — Missing comma and retry behavior
# ==============================================================================
def test_missing_comma_raises_and_retries_recover():
    # Missing comma between recommendation and confidence
    malformed_missing_comma = """{
  "schema_version": "1.0",
  "scenario_id": "normal-001",
  "ticker": "AAPL",
  "sentiment": "positive",
  "price_impact": "positive",
  "recommendation": "BUY"
  "confidence": 0.8,
  "forecast_horizon": "short_term"
}"""
    # Direct parsing must raise JSONDecodeError with 'Expecting delimiter'
    with pytest.raises(json.JSONDecodeError) as exc_info:
        _json(malformed_missing_comma)
    assert "Expecting ',' delimiter" in str(exc_info.value)

    # When calling with retry: initial call fails, retry call returns valid JSON
    mock_db = MagicMock()
    mock_resp_fail = {"choices": [{"message": {"content": malformed_missing_comma}}]}
    mock_resp_ok = {"choices": [{"message": {"content": json.dumps(VALID_FINANCIAL_OUTPUT)}}]}

    with patch("app.services.providers.generate", side_effect=[mock_resp_fail, mock_resp_ok]) as mock_gen:
        output, raw, retries = _call_and_parse_with_retry(
            mock_db,
            "prov_1",
            [{"role": "user", "content": "analyze"}],
            {"provider_id": "prov_1"},
            FinancialNewsOutput,
            max_retries=2,
        )
        assert output.recommendation == "BUY"
        assert len(retries) == 1
        assert "Expecting ',' delimiter" in retries[0]["error"]
        assert mock_gen.call_count == 2
        # Verify corrective prompt was passed in second call
        second_call_messages = mock_gen.call_args_list[1][0][2]
        assert any("could not be parsed as valid JSON" in m.get("content", "") for m in second_call_messages)


# ==============================================================================
# Test 4 — Truncated JSON exhausts retries and raises ModelOutputInvalidError
# ==============================================================================
def test_truncated_json_exhausts_retries():
    truncated_json = '{"schema_version": "1.0", "scenario_id": "normal-001", "sentiment": "pos'
    
    mock_db = MagicMock()
    mock_resp_fail = {"choices": [{"message": {"content": truncated_json}}]}

    with patch("app.services.providers.generate", return_value=mock_resp_fail) as mock_gen:
        with pytest.raises(ModelOutputInvalidError) as exc_info:
            _call_and_parse_with_retry(
                mock_db,
                "prov_1",
                [{"role": "user", "content": "analyze"}],
                {"provider_id": "prov_1"},
                FinancialNewsOutput,
                max_retries=2,
            )
        assert exc_info.value.raw_response == mock_resp_fail
        assert len(exc_info.value.retry_history) == 3  # initial + 2 retries
        assert mock_gen.call_count == 3


# ==============================================================================
# Test 5 — Baseline integration with valid response and error preservation
# ==============================================================================
def test_baseline_integration_success_and_failure():
    mock_db = MagicMock()
    agent = FinancialNewsAnalysisAgent(mock_db)

    # 5a: Successful execution
    mock_resp_ok = {"choices": [{"message": {"content": json.dumps(VALID_FINANCIAL_OUTPUT)}}]}
    with patch("app.services.providers.generate", return_value=mock_resp_ok):
        res = agent.run(SAMPLE_INPUT_PAYLOAD, configuration={"provider_id": "prov_1"})
        assert res.run_status == "completed"
        assert res.normalized_output["recommendation"] == "BUY"
        assert res.raw_output == mock_resp_ok
        assert res.error_code is None

    # 5b: Permanent malformed output returns MODEL_OUTPUT_INVALID and preserves raw_output
    malformed = '{"invalid json missing closing'
    mock_resp_fail = {"choices": [{"message": {"content": malformed}}]}
    with patch("app.services.providers.generate", return_value=mock_resp_fail):
        res_fail = agent.run(SAMPLE_INPUT_PAYLOAD, configuration={"provider_id": "prov_1"})
        assert res_fail.run_status == "failed"
        assert res_fail.error_code == "MODEL_OUTPUT_INVALID"
        assert res_fail.raw_output == mock_resp_fail
        assert "retries" in res_fail.metadata


# ==============================================================================
# Test 6 — EGAL integration through normal pipeline stages
# ==============================================================================
def test_egal_integration_pipeline_stages():
    mock_db = MagicMock()
    agent = FinancialNewsEgalAgent(mock_db)

    mock_resp_ok = {"choices": [{"message": {"content": json.dumps(VALID_FINANCIAL_OUTPUT)}}]}
    with patch("app.services.providers.generate", return_value=mock_resp_ok):
        res = agent.run(SAMPLE_INPUT_PAYLOAD, configuration={"provider_id": "prov_1"})
        assert res.run_status == "completed"
        assert res.normalized_output["schema_version"] == "1.0"
        assert "abstention" in res.normalized_output
        assert "final_claim_validation" in res.normalized_output
        assert "final_evidence_sufficiency" in res.normalized_output
        assert "audit" in res.normalized_output
        # Check raw output preserves original completion
        assert res.raw_output["original_completion"] == mock_resp_ok
        assert res.error_code is None
