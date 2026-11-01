import hashlib, json, re, shutil, uuid
from pathlib import Path
from jsonschema import Draft202012Validator
from sqlalchemy.orm import Session
from sqlalchemy.exc import IntegrityError
from fastapi import HTTPException
from app.core.config import settings
from app.models.entities import Dataset, DatasetSnapshot
from app.schemas.financial_news import FinancialNewsDatasetRecord

def parse_declared_schema(value):
    """Normalize the multipart JSON value to its canonical parsed JSON object."""
    if value is None or value == "": return None
    if isinstance(value, (dict, bool)): schema=value
    elif isinstance(value, bytes):
        try: schema=json.loads(value.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc: raise ValueError("declared_schema must contain a JSON object") from exc
    elif isinstance(value, str):
        try: schema=json.loads(value)
        except json.JSONDecodeError as exc:
            hint="; do not append a JavaScript object directly to FormData—send JSON text or an application/json file part" if value == "[object Object]" else ""
            raise ValueError("declared_schema must contain a JSON object" + hint) from exc
    else: raise ValueError("declared_schema must be a JSON object")
    if not isinstance(schema, dict): raise ValueError("declared_schema must be a JSON object")
    try: Draft202012Validator.check_schema(schema)
    except Exception as exc: raise ValueError(f"declared_schema is not a valid JSON Schema: {exc}") from exc
    return schema

async def schema_from_multipart(form):
    """Read a schema field from either a JSON text field or a JSON file part."""
    value = form.get("declared_schema")
    if hasattr(value, "read"):
        value = await value.read()
    return parse_declared_schema(value)

def uid(prefix): return f"{prefix}_{uuid.uuid4().hex}"
def safe_name(name): return re.sub(r"[^A-Za-z0-9._-]", "_", Path(name or "dataset").name)[:200]
def fingerprint(path):
    digest = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""): digest.update(block)
    return digest.hexdigest()
def _records(path: Path, fmt: str):
    if fmt == "jsonl":
        with path.open("r", encoding="utf-8") as f:
            for i, line in enumerate(f, 1):
                if line.strip():
                    try: yield i, json.loads(line)
                    except json.JSONDecodeError as exc: raise ValueError(f"JSONL line {i}: {exc.msg}") from exc
    else:
        with path.open("r", encoding="utf-8") as f: data = json.load(f)
        if not isinstance(data, list): raise ValueError("JSON dataset must be a top-level array")
        for i, record in enumerate(data): yield i, record
def validate(dataset: Dataset):
    errors, warnings, count = [], [], 0
    validator = Draft202012Validator(dataset.declared_schema) if dataset.declared_schema else None
    try:
        for loc, record in _records(Path(dataset.storage_path), dataset.format):
            count += 1
            if not isinstance(record, dict): errors.append({"record": loc, "message": "record must be an object"})
            elif validator:
                for err in validator.iter_errors(record): errors.append({"record": loc, "message": err.message})
            if isinstance(record,dict) and record.get("record_schema_version") == "1.0":
                try: FinancialNewsDatasetRecord.model_validate(record)
                except Exception as exc: errors.append({"record":loc,"message":f"financial-news v1: {exc}"})
            if len(errors) >= settings.jsonl_error_sample_limit: break
        if count == 0: errors.append({"message": "dataset contains no records"})
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc: errors.append({"message": str(exc)})
    dataset.record_count = count if not errors else None
    dataset.validation_errors, dataset.validation_warnings = errors, warnings
    dataset.validation_status = "valid" if not errors else "invalid"
    return dataset
def records_page(dataset: Dataset, offset: int, limit: int):
    page=[]
    try:
        for loc, record in _records(Path(dataset.storage_path), dataset.format):
            zero = loc - 1 if dataset.format == "jsonl" else loc
            if zero < offset: continue
            if len(page) == limit: break
            page.append({"index": zero, "record": record})
    except Exception as exc: raise HTTPException(422, detail={"code":"DATASET_READ_ERROR","message":str(exc)})
    return page
def snapshot(db: Session, dataset: Dataset):
    dest = settings.storage_dir / "snapshots" / f"{dataset.id}-{dataset.fingerprint}.{dataset.format}"
    existing = db.query(DatasetSnapshot).filter(
        (DatasetSnapshot.storage_path == str(dest)) |
        ((DatasetSnapshot.dataset_id == dataset.id) & (DatasetSnapshot.fingerprint == dataset.fingerprint))
    ).first()
    if existing:
        if not dest.exists():
            shutil.copyfile(dataset.storage_path, dest)
        return existing

    if not dest.exists():
        shutil.copyfile(dataset.storage_path, dest)
    item = DatasetSnapshot(id=uid("snap"), dataset_id=dataset.id, fingerprint=dataset.fingerprint, storage_path=str(dest))
    try:
        db.add(item)
        db.commit()
        db.refresh(item)
        return item
    except IntegrityError:
        db.rollback()
        existing = db.query(DatasetSnapshot).filter(
            (DatasetSnapshot.storage_path == str(dest)) |
            ((DatasetSnapshot.dataset_id == dataset.id) & (DatasetSnapshot.fingerprint == dataset.fingerprint))
        ).first()
        if existing:
            return existing
        raise
