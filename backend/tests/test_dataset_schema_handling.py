import json
from tempfile import TemporaryDirectory
from pathlib import Path
from app.models.entities import Dataset
from app.services.datasets import parse_declared_schema, validate

RECORD={"record_schema_version":"1.0","scenario_id":"NORMAL-001","category":"normal","input":{"schema_version":"1.0","scenario_id":"NORMAL-001","ticker":"AAPL","company_name":"Apple","task":"Analyze.","retrieval_mode":"provided_evidence","search_query":None,"evidence":[],"ml_forecast":None},"ground_truth":{"annotation_version":"1.0","expected_task_completion":True,"stance":"positive"},"metadata":{"source_mode":"test"}}

def make_dataset(tmp_path, content, fmt="jsonl", schema=None):
    path=tmp_path / f"sample.{fmt}"; path.write_text(content,encoding="utf-8")
    return Dataset(id="ds_test",display_name="test",original_filename=path.name,format=fmt,size_bytes=path.stat().st_size,fingerprint="0"*64,storage_path=str(path),declared_schema=schema)

def test_declared_schema_is_normalized_to_an_object():
    assert parse_declared_schema({"type":"object"}) == {"type":"object"}
    assert parse_declared_schema('{"type":"object"}') == {"type":"object"}
    assert parse_declared_schema(b'{"type":"object"}') == {"type":"object"}
    try: parse_declared_schema("[object Object]")
    except ValueError as exc: assert "FormData" in str(exc)
    else: assert False, "object coercion must be rejected clearly"

def test_jsonl_financial_records_validate_and_invalid_line_has_number():
    with TemporaryDirectory(dir=Path(__file__).parent) as folder:
        folder=Path(folder)
        dataset=make_dataset(folder,json.dumps(RECORD)+"\n"+json.dumps({**RECORD,"scenario_id":"NORMAL-002","input":{**RECORD["input"],"scenario_id":"NORMAL-002"}})+"\n")
        validate(dataset); assert dataset.validation_status == "valid" and dataset.record_count == 2
        bad=make_dataset(folder,json.dumps(RECORD)+"\nINVALID JSON\n")
        validate(bad); assert "JSONL line 2" in bad.validation_errors[0]["message"]

def test_financial_envelope_remains_strict_and_json_arrays_work():
    with TemporaryDirectory(dir=Path(__file__).parent) as folder:
        folder=Path(folder)
        missing=make_dataset(folder,json.dumps({"record_schema_version":"1.0","scenario_id":"NORMAL-001","category":"normal"})+"\n")
        validate(missing); assert missing.validation_status == "invalid"
        array=make_dataset(folder,json.dumps([RECORD]),fmt="json")
        validate(array); assert array.validation_status == "valid" and array.record_count == 1
