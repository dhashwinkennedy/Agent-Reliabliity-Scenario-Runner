import csv, io, json, shutil, uuid
from datetime import datetime
from pathlib import Path
from typing import Literal
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
from app.database.session import get_db, SessionLocal
from app.models.entities import (
    Dataset,
    DatasetSnapshot,
    Experiment,
    ExperimentGroup,
    ExperimentRepetition,
    Run,
    AgentRegistration,
    ProviderConfiguration,
    Evaluation,
    RunEvaluation,
    ConsistencyAggregation,
)
from app.core.config import settings
from app.services.datasets import safe_name, fingerprint, validate, records_page, snapshot, uid, schema_from_multipart
from app.services.experiments import create_runs, start, to_json_safe, create_repetition
from app.integrations.registry import agents, providers, resolve_agent, list_agent_metadata, registration_metadata, SUPPORTED_CUSTOM_ADAPTERS, schema_errors
from app.schemas.api import (
    ExperimentCreate,
    AgentRegistrationCreate,
    AgentRegistrationUpdate,
    AgentTestRequest,
    ProviderCreate,
    ProviderUpdate,
    EvaluationCreate,
    ConsistencyAggregationCreate,
    ExperimentRerunRequest,
    ExperimentGroupCreate,
    ExperimentGroupLink,
)
from app.schemas.analysis import AnalysisFilterRequest, AnalysisOptionsResponse, AnalysisReportResponse
from app.services import providers as provider_service
from app.services import evaluation as evaluation_service
from app.services import consistency as consistency_service
from app.services import analysis as analysis_service
from app.services import grouping as grouping_service

router=APIRouter()
def has_inline_secret(value):
    if isinstance(value,dict):
        return any(any(word in str(k).lower() for word in ("secret","password","token","api_key","authorization")) or has_inline_secret(v) for k,v in value.items())
    if isinstance(value,list): return any(has_inline_secret(v) for v in value)
    return False
def missing(kind): raise HTTPException(404, detail={"code":"NOT_FOUND","message":f"{kind} not found"})
def dataset_out(d): return {"id":d.id,"display_name":d.display_name,"original_filename":d.original_filename,"format":d.format,"size_bytes":d.size_bytes,"record_count":d.record_count,"fingerprint":d.fingerprint,"validation_status":d.validation_status,"validation_errors":d.validation_errors,"validation_warnings":d.validation_warnings,"created_at":d.created_at}
def exp_out(e):
    m = getattr(e, "model", None)
    if not m and isinstance(e.provider_metadata_snapshot, dict):
        m = e.provider_metadata_snapshot.get("model") or e.provider_metadata_snapshot.get("default_model")
    return {
        "id": e.id,
        "name": e.name,
        "group_id": getattr(e, "group_id", None),
        "group_name": getattr(e, "group_name", None),
        "dataset_snapshot_id": e.dataset_snapshot_id,
        "agent_id": e.agent_id,
        "agent_version": e.agent_version,
        "agent_configuration_snapshot": e.agent_configuration_snapshot,
        "provider_id": e.provider_id,
        "model": m,
        "input_mapping": e.input_mapping,
        "status": e.status,
        "created_at": e.created_at,
    }

def repetition_out(rep, db: Session | None = None):
    return grouping_service.repetition_summary(rep, db)
@router.get("/health")
def health(): return {"status":"ok","service":"ai-agent-evaluation-platform"}
@router.post("/datasets/upload", status_code=201)
async def upload(request: Request, file: UploadFile=File(...), display_name: str|None=Form(None), db:Session=Depends(get_db)):
    name=safe_name(file.filename or "dataset"); ext=Path(name).suffix.lower().lstrip(".")
    if ext not in {"json","jsonl"}: raise HTTPException(415,detail={"code":"UNSUPPORTED_DATASET_FORMAT","message":"Only .json and .jsonl are supported"})
    destination=settings.storage_dir / "datasets" / f"{uuid.uuid4().hex}-{name}"; total=0
    with destination.open("wb") as out:
        while chunk:=await file.read(1024*1024):
            total+=len(chunk)
            if total>settings.max_upload_bytes: out.close(); destination.unlink(missing_ok=True); raise HTTPException(413,detail={"code":"UPLOAD_TOO_LARGE","message":"Upload exceeds configured limit"})
            out.write(chunk)
    try:
        schema=await schema_from_multipart(await request.form())
    except ValueError as exc: destination.unlink(missing_ok=True); raise HTTPException(422,detail={"code":"SCHEMA_INVALID","message":str(exc)})
    d=Dataset(id=uid("ds"),display_name=display_name or Path(name).stem,original_filename=name,format=ext,size_bytes=total,fingerprint=fingerprint(destination),storage_path=str(destination),declared_schema=schema)
    validate(d); db.add(d); db.commit(); db.refresh(d); return dataset_out(d)
@router.get("/datasets")
def list_datasets(offset: int = Query(0, ge=0), limit: int = Query(50, ge=1, le=settings.max_page_size), db: Session = Depends(get_db)):
    total = db.query(Dataset).count()
    items = db.query(Dataset).order_by(Dataset.created_at.desc()).offset(offset).limit(limit).all()
    has_more = (offset + len(items)) < total
    next_offset = (offset + len(items)) if has_more else None
    return {
        "items": [dataset_out(x) for x in items],
        "offset": offset,
        "limit": limit,
        "total": total,
        "has_more": has_more,
        "next_offset": next_offset,
    }
@router.get("/datasets/{dataset_id}")
def get_dataset(dataset_id:str,db:Session=Depends(get_db)):
    d=db.get(Dataset,dataset_id); return dataset_out(d) if d else missing("Dataset")
@router.post("/datasets/{dataset_id}/validate")
def revalidate(dataset_id:str,db:Session=Depends(get_db)):
    d=db.get(Dataset,dataset_id)
    if not d: missing("Dataset")
    validate(d); db.commit(); return dataset_out(d)
@router.get("/datasets/{dataset_id}/records")
def get_records(dataset_id: str, offset: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=settings.max_page_size), db: Session = Depends(get_db)):
    d = db.get(Dataset, dataset_id)
    if not d: missing("Dataset")
    items = records_page(d, offset, limit)
    total = d.record_count
    if total is None:
        try:
            total = sum(1 for _ in _records(Path(d.storage_path), d.format))
        except Exception:
            total = len(items)
    has_more = (offset + len(items)) < total
    next_offset = (offset + len(items)) if has_more else None
    return {
        "items": items,
        "offset": offset,
        "limit": limit,
        "total": total,
        "has_more": has_more,
        "next_offset": next_offset,
    }
@router.post("/datasets/{dataset_id}/snapshots",status_code=201)
def create_snapshot(dataset_id:str,db:Session=Depends(get_db)):
    d=db.get(Dataset,dataset_id)
    if not d: missing("Dataset")
    if d.validation_status!="valid": raise HTTPException(409,detail={"code":"DATASET_NOT_VALID","message":"Validate a valid dataset before snapshotting"})
    s=snapshot(db,d); return {"id":s.id,"dataset_id":s.dataset_id,"fingerprint":s.fingerprint,"created_at":s.created_at}
@router.delete("/datasets/{dataset_id}",status_code=204)
def delete_dataset(dataset_id:str,db:Session=Depends(get_db)):
    d=db.get(Dataset,dataset_id)
    if not d: missing("Dataset")
    if db.query(DatasetSnapshot).filter_by(dataset_id=dataset_id).first(): raise HTTPException(409,detail={"code":"DATASET_REFERENCED","message":"Datasets with snapshots are retained for reproducibility"})
    Path(d.storage_path).unlink(missing_ok=True); db.delete(d); db.commit()
@router.get("/agents")
def list_agents(db:Session=Depends(get_db)): return {"items":list_agent_metadata(db)}
@router.get("/agents/{agent_id}")
def get_agent(agent_id:str,db:Session=Depends(get_db)):
    agent=resolve_agent(db,agent_id); return agent.metadata() if agent else missing("Agent")
@router.post("/agents",status_code=201)
def register_agent(body:AgentRegistrationCreate,db:Session=Depends(get_db)):
    if body.id in agents or db.get(AgentRegistration,body.id): raise HTTPException(409,detail={"code":"AGENT_ID_CONFLICT","message":"Agent ID already exists"})
    if body.adapter_type not in SUPPORTED_CUSTOM_ADAPTERS: raise HTTPException(422,detail={"code":"ADAPTER_UNSUPPORTED","message":"Adapter type is not supported"})
    if has_inline_secret(body.adapter_config): raise HTTPException(422,detail={"code":"INLINE_SECRET_FORBIDDEN","message":"Use a future secret reference; plaintext credentials are not accepted"})
    if (body.adapter_type=="mock") != (body.agent_type=="custom_python"): raise HTTPException(422,detail={"code":"ADAPTER_TYPE_MISMATCH","message":"mock requires custom_python; http requires external_http"})
    for name,schema in (("input_schema",body.input_schema),("output_schema",body.output_schema),("configuration_schema",body.configuration_schema)):
        try:
            if schema: __import__("jsonschema").Draft202012Validator.check_schema(schema)
        except Exception as exc: raise HTTPException(422,detail={"code":"SCHEMA_INVALID","message":f"{name}: {exc}"})
    item=AgentRegistration(**body.model_dump(),status="registered"); db.add(item); db.commit(); db.refresh(item)
    adapter=resolve_agent(db,item.id); errors=adapter.validate_configuration(item.adapter_config)
    if not errors: item.status="ready"; db.commit(); db.refresh(item)
    return {**registration_metadata(item),"validation_errors":errors}
@router.put("/agents/{agent_id}")
def update_agent(agent_id:str,body:AgentRegistrationUpdate,db:Session=Depends(get_db)):
    item=db.get(AgentRegistration,agent_id)
    if not item: missing("Custom agent")
    if item.status=="retired": raise HTTPException(409,detail={"code":"AGENT_RETIRED","message":"Retired agent cannot be updated"})
    if body.adapter_config is not None and has_inline_secret(body.adapter_config): raise HTTPException(422,detail={"code":"INLINE_SECRET_FORBIDDEN","message":"Plaintext credentials are not accepted"})
    for key,value in body.model_dump(exclude_unset=True).items(): setattr(item,key,value)
    for name in ("input_schema","output_schema","configuration_schema"):
        schema=getattr(item,name)
        try:
            if schema: __import__("jsonschema").Draft202012Validator.check_schema(schema)
        except Exception as exc: raise HTTPException(422,detail={"code":"SCHEMA_INVALID","message":f"{name}: {exc}"})
    adapter=resolve_agent(db,agent_id); errors=adapter.validate_configuration(item.adapter_config); item.status="ready" if not errors else "registered"; db.commit(); db.refresh(item)
    return {**registration_metadata(item),"validation_errors":errors}
@router.post("/agents/{agent_id}/validate")
def validate_agent(agent_id:str,db:Session=Depends(get_db)):
    agent=resolve_agent(db,agent_id)
    if not agent: missing("Agent")
    item=db.get(AgentRegistration,agent_id); errors=agent.validate_configuration(item.adapter_config) if item else []
    if item: item.status="ready" if not errors else "registered"; db.commit()
    return {"agent_id":agent_id,"valid":not errors,"errors":errors}
@router.post("/agents/{agent_id}/test")
def test_agent(agent_id:str,body:AgentTestRequest,db:Session=Depends(get_db)):
    agent=resolve_agent(db,agent_id)
    if not agent: missing("Agent")
    if not agent.metadata().get("ready"): raise HTTPException(409,detail={"code":"AGENT_UNAVAILABLE","message":"Agent is not ready"})
    if has_inline_secret(body.configuration): raise HTTPException(422,detail={"code":"INLINE_SECRET_FORBIDDEN","message":"Plaintext credentials are not accepted"})
    errors=agent.validate_configuration(body.configuration)+agent.validate_input(body.input)
    if errors: raise HTTPException(422,detail={"code":"AGENT_TEST_INVALID","message":"; ".join(errors)})
    result=agent.run(body.input,providers.get("mock"),body.configuration)
    return {"test_execution":True,**result.model_dump()}
@router.post("/agents/{agent_id}/enable")
def enable_agent(agent_id:str,db:Session=Depends(get_db)):
    item=db.get(AgentRegistration,agent_id)
    if not item: missing("Custom agent")
    agent=resolve_agent(db,agent_id)
    errors=agent.validate_configuration(item.adapter_config) if agent else ["adapter unavailable"]
    if errors: raise HTTPException(422,detail={"code":"AGENT_CONFIGURATION_INVALID","message":"; ".join(errors)})
    item.status="ready"; db.commit(); return registration_metadata(item)
@router.post("/agents/{agent_id}/disable")
def disable_agent(agent_id:str,db:Session=Depends(get_db)):
    item=db.get(AgentRegistration,agent_id)
    if not item: missing("Custom agent")
    item.status="disabled"; db.commit(); return registration_metadata(item)
@router.delete("/agents/{agent_id}",status_code=204)
def retire_agent(agent_id:str,db:Session=Depends(get_db)):
    item=db.get(AgentRegistration,agent_id)
    if not item: missing("Custom agent")
    item.status="retired"; db.commit()
def provider_error(exc):
    raise HTTPException(exc.status, detail={"code":exc.code,"message":exc.message})
@router.get("/providers")
def list_providers(db:Session=Depends(get_db)):
    return {"items":[provider_service.metadata(x) for x in db.query(ProviderConfiguration).order_by(ProviderConfiguration.created_at.desc()).all()]}
@router.post("/providers", status_code=201)
def create_provider(body:ProviderCreate, db:Session=Depends(get_db)):
    try: base_url=provider_service._url(body.base_url)
    except provider_service.ProviderError as exc: provider_error(exc)
    provider_id=body.id or uid("provider")
    if db.get(ProviderConfiguration,provider_id): raise HTTPException(409,detail={"code":"PROVIDER_ID_CONFLICT","message":"Provider ID already exists"})
    try: encrypted=provider_service.encrypt_api_key(body.api_key) if body.api_key else None
    except provider_service.ProviderError as exc: provider_error(exc)
    item=ProviderConfiguration(id=provider_id,display_name=body.name,provider_type=body.provider_type,base_url=base_url,model=body.default_model,encrypted_api_key=encrypted,timeout_seconds=body.timeout_seconds,active=body.is_active,generation_parameters=body.generation_parameters)
    db.add(item); db.commit(); db.refresh(item); return provider_service.metadata(item)
@router.get("/providers/{provider_id}")
def get_provider(provider_id:str,db:Session=Depends(get_db)):
    try: return provider_service.metadata(provider_service.get_provider(db,provider_id,False))
    except provider_service.ProviderError as exc: provider_error(exc)
@router.patch("/providers/{provider_id}")
def update_provider(provider_id:str,body:ProviderUpdate,db:Session=Depends(get_db)):
    try: item=provider_service.get_provider(db,provider_id,False)
    except provider_service.ProviderError as exc: provider_error(exc)
    values=body.model_dump(exclude_unset=True)
    try:
        if "base_url" in values: item.base_url=provider_service._url(values.pop("base_url"))
        if "api_key" in values:
            api_key=values.pop("api_key")
            if api_key is None: raise HTTPException(422,detail={"code":"API_KEY_CLEAR_AMBIGUOUS","message":"Use clear_api_key=true to remove a credential"})
            item.encrypted_api_key=provider_service.encrypt_api_key(api_key)
    except provider_service.ProviderError as exc: provider_error(exc)
    if values.pop("clear_api_key",False): item.encrypted_api_key=None
    mapping={"name":"display_name","default_model":"model","is_active":"active"}
    for key,value in values.items(): setattr(item,mapping.get(key,key),value)
    db.commit(); db.refresh(item); return provider_service.metadata(item)
@router.delete("/providers/{provider_id}",status_code=204)
def delete_provider(provider_id:str,db:Session=Depends(get_db)):
    try: item=provider_service.get_provider(db,provider_id,False)
    except provider_service.ProviderError as exc: provider_error(exc)
    if db.query(Experiment).filter_by(provider_id=provider_id).first(): raise HTTPException(409,detail={"code":"PROVIDER_REFERENCED","message":"Provider is referenced by historical experiments and cannot be deleted; deactivate it instead"})
    db.delete(item); db.commit()
@router.get("/providers/{provider_id}/models")
def provider_models(provider_id:str,db:Session=Depends(get_db)):
    try:
        item=provider_service.get_provider(db,provider_id,False)
        return {"provider_id":provider_id,"items":provider_service.discover_models(item),"manual_model_supported":True}
    except provider_service.ProviderError as exc: provider_error(exc)
@router.get("/models")
def models(db:Session=Depends(get_db)): return {"items":[m for p in providers.values() for m in p.metadata().get("models",[])]+[x.model for x in db.query(ProviderConfiguration).filter_by(active=True)]}
@router.post("/providers/{provider_id}/test-connection")
def test_provider(provider_id:str,db:Session=Depends(get_db)):
    try: return {"provider_id":provider_id,**provider_service.connection_test(provider_service.get_provider(db,provider_id,False))}
    except provider_service.ProviderError as exc: provider_error(exc)
@router.post("/experiments",status_code=201)
def create_experiment(body:ExperimentCreate,db:Session=Depends(get_db)):
    if not db.get(DatasetSnapshot,body.dataset_snapshot_id): missing("Dataset snapshot")
    if has_inline_secret(body.agent_configuration): raise HTTPException(422,detail={"code":"INLINE_SECRET_FORBIDDEN","message":"Plaintext credentials are not accepted"})
    agent=resolve_agent(db,body.agent_id)
    if not agent or not agent.metadata().get("ready"): raise HTTPException(422,detail={"code":"AGENT_UNAVAILABLE","message":"Agent is unavailable, disabled, or not implemented"})
    errors=agent.validate_configuration(body.agent_configuration)
    if errors: raise HTTPException(422,detail={"code":"AGENT_CONFIGURATION_INVALID","message":"; ".join(errors)})
    provider_snapshot=None
    if body.provider_id not in providers:
        try: provider_snapshot=provider_service.metadata(provider_service.get_provider(db,body.provider_id))
        except provider_service.ProviderError as exc: provider_error(exc)
    else: provider_snapshot=providers[body.provider_id].metadata()
    values=body.model_dump()
    configuration=to_json_safe(values.pop("agent_configuration"))
    safe_provider=to_json_safe(provider_snapshot)
    
    # Model resolution: explicit body.model takes precedence, then provider default model
    chosen_model = body.model or (provider_snapshot.get("default_model") or provider_snapshot.get("model") if isinstance(provider_snapshot, dict) else None)
    if not chosen_model and body.provider_id in providers:
        prov_models = providers[body.provider_id].metadata().get("models", [])
        if prov_models:
            chosen_model = prov_models[0]
            
    values["model"] = chosen_model
    if safe_provider and isinstance(safe_provider, dict) and chosen_model:
        safe_provider["model"] = chosen_model
        
    safe_values={k:to_json_safe(v) for k,v in values.items()}
    if body.group_id:
        existing_grp = db.get(ExperimentGroup, body.group_id)
        if existing_grp:
            if existing_grp.dataset_snapshot_id != body.dataset_snapshot_id or existing_grp.provider_id != body.provider_id or (chosen_model and existing_grp.model and existing_grp.model != chosen_model):
                raise HTTPException(422, detail={"code": "INCOMPATIBLE_EXPERIMENT_GROUP", "message": "Experiment does not match existing group conditions"})
        else:
            new_grp = ExperimentGroup(
                id=body.group_id,
                name=body.group_name or body.name,
                dataset_snapshot_id=body.dataset_snapshot_id,
                provider_id=body.provider_id,
                model=chosen_model,
            )
            db.add(new_grp)
    e=Experiment(id=uid("exp"),agent_version=agent.metadata().get("version","unknown"),agent_configuration_snapshot=configuration,provider_metadata_snapshot=safe_provider,**safe_values)
    db.add(e); db.commit(); db.refresh(e); return exp_out(e)
@router.get("/experiments")
def list_experiments(db:Session=Depends(get_db)): return {"items":[exp_out(x) for x in db.query(Experiment).order_by(Experiment.created_at.desc()).all()]}

@router.post("/evaluations/consistency-aggregations", status_code=201)
@router.post("/experiments/consistency-aggregations", status_code=201)
def create_consistency_aggregation(body: ConsistencyAggregationCreate | None = None, db: Session = Depends(get_db)):
    eval_ids = body.evaluation_ids if body and body.evaluation_ids else []
    if not eval_ids:
        completed_exps = db.query(Experiment).filter_by(status="completed").all()
        eval_ids = []
        for exp in completed_exps:
            latest_ev = db.query(Evaluation).filter_by(experiment_id=exp.id, status="completed").order_by(Evaluation.created_at.desc()).first()
            if latest_ev and latest_ev.id not in eval_ids:
                eval_ids.append(latest_ev.id)
    try:
        agg = consistency_service.aggregate_consistency(db, eval_ids, persist=True)
    except ValueError as exc:
        raise HTTPException(400, detail={"code": "INVALID_EVALUATION_SET", "message": str(exc)})
    return consistency_service.consistency_aggregation_out(agg)

@router.get("/evaluations/consistency-aggregations")
@router.get("/experiments/consistency-aggregations")
def list_consistency_aggregations(db: Session = Depends(get_db)):
    items = db.query(ConsistencyAggregation).order_by(ConsistencyAggregation.created_at.desc()).all()
    return {"items": [consistency_service.consistency_aggregation_out(x) for x in items]}

@router.get("/evaluations/consistency-aggregations/{aggregation_id}")
@router.get("/experiments/consistency-aggregations/{aggregation_id}")
def get_consistency_aggregation(aggregation_id: str, db: Session = Depends(get_db)):
    item = db.get(ConsistencyAggregation, aggregation_id)
    if not item:
        missing("Consistency aggregation")
    return consistency_service.consistency_aggregation_out(item)

@router.get("/experiments/{experiment_id}")
def get_experiment(experiment_id:str,db:Session=Depends(get_db)):
    e=db.get(Experiment,experiment_id); return exp_out(e) if e else missing("Experiment")
@router.post("/experiments/{experiment_id}/start")
def start_experiment(experiment_id:str,db:Session=Depends(get_db)):
    e=db.get(Experiment,experiment_id)
    if not e: missing("Experiment")
    if e.status not in {"draft","paused"}: raise HTTPException(409,detail={"code":"INVALID_EXPERIMENT_STATE","message":"Only draft or paused experiments can start"})
    if e.status=="draft":
        rep = db.query(ExperimentRepetition).filter_by(experiment_id=e.id, repetition_index=1).first()
        if not rep:
            rep = ExperimentRepetition(
                id=uid("rep"),
                experiment_id=e.id,
                repetition_index=1,
                status="starting",
                created_at=datetime.utcnow(),
                started_at=datetime.utcnow(),
            )
            db.add(rep)
            db.flush()
        new_runs = create_runs(db, e, repetition_id=rep.id, repetition_index=1)
        rep.run_count = len(new_runs)
        db.commit()
    e.status="starting"; db.commit(); start(SessionLocal,e.id); return exp_out(e)

def run_out(x):
    return {
        "id": x.id,
        "experiment_id": x.experiment_id,
        "repetition_id": getattr(x, "repetition_id", None),
        "repetition_index": getattr(x, "repetition_index", None) or 1,
        "record_index": x.record_index,
        "status": x.status,
        "raw_output": x.raw_output,
        "normalized_output": x.normalized_output,
        "output": x.output,
        "execution_duration_ms": x.execution_duration_ms,
        "error": x.error,
        "started_at": x.started_at,
        "completed_at": x.completed_at,
    }

@router.get("/experiments/{experiment_id}/runs")
def runs(
    experiment_id: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=settings.max_page_size),
    repetition_id: str | None = None,
    repetition_index: int | None = None,
    db: Session = Depends(get_db),
):
    if not isinstance(repetition_id, str): repetition_id = None
    if not isinstance(repetition_index, int): repetition_index = None
    exp = db.get(Experiment, experiment_id)
    if not exp: missing("Experiment")
    query = db.query(Run).filter_by(experiment_id=experiment_id)
    if repetition_id:
        query = query.filter(Run.repetition_id == repetition_id)
    elif repetition_index is not None:
        query = query.filter(Run.repetition_index == repetition_index)
    total = query.count()
    items = query.order_by(Run.record_index).offset(offset).limit(limit).all()
    has_more = (offset + len(items)) < total
    next_offset = (offset + len(items)) if has_more else None
    
    expected_run_count = total
    snap = db.get(DatasetSnapshot, exp.dataset_snapshot_id) if exp.dataset_snapshot_id else None
    if snap:
        dataset = db.get(Dataset, snap.dataset_id) if snap.dataset_id else None
        if dataset and dataset.record_count is not None:
            expected_run_count = dataset.record_count
        else:
            try:
                expected_run_count = sum(1 for _ in _records(Path(snap.storage_path), Path(snap.storage_path).suffix.lstrip(".")))
            except Exception:
                expected_run_count = total

    return {
        "items": [run_out(x) for x in items],
        "offset": offset,
        "limit": limit,
        "total": total,
        "has_more": has_more,
        "next_offset": next_offset,
        "total_persisted_runs": total,
        "expected_run_count": expected_run_count,
    }

@router.get("/runs/{run_id}")
def get_run(run_id:str,db:Session=Depends(get_db)):
    r=db.get(Run,run_id); return run_out(r) if r else missing("Run")

@router.get("/experiments/{experiment_id}/events")
def events(experiment_id:str,db:Session=Depends(get_db)):
    e=db.get(Experiment,experiment_id)
    if not e: missing("Experiment")
    counts={s:db.query(Run).filter_by(experiment_id=e.id,status=s).count() for s in ("queued","running","completed","failed")}
    def stream(): yield f"event: progress\ndata: {json.dumps({'experiment_id':e.id,'status':e.status,'runs':counts})}\n\n"
    return StreamingResponse(stream(),media_type="text/event-stream")

@router.get("/experiments/{experiment_id}/results")
def results(
    experiment_id: str,
    offset: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1, le=settings.max_page_size),
    all: bool = Query(False, description="Return all experiment runs without pagination"),
    repetition_id: str | None = None,
    repetition_index: int | None = None,
    db: Session = Depends(get_db)
):
    if not isinstance(repetition_id, str): repetition_id = None
    if not isinstance(repetition_index, int): repetition_index = None
    exp = db.get(Experiment, experiment_id)
    if not exp: missing("Experiment")
    query = db.query(Run).filter_by(experiment_id=experiment_id)
    if repetition_id:
        query = query.filter(Run.repetition_id == repetition_id)
    elif repetition_index is not None:
        query = query.filter(Run.repetition_index == repetition_index)
    query = query.order_by(Run.record_index)
    total = query.count()
    
    if all or limit is None:
        items = query.all()
        actual_offset = 0
        actual_limit = total
        has_more = False
        next_offset = None
    else:
        items = query.offset(offset).limit(limit).all()
        actual_offset = offset
        actual_limit = limit
        has_more = (offset + len(items)) < total
        next_offset = (offset + len(items)) if has_more else None

    expected_run_count = total
    snap = db.get(DatasetSnapshot, exp.dataset_snapshot_id) if exp.dataset_snapshot_id else None
    if snap:
        dataset = db.get(Dataset, snap.dataset_id) if snap.dataset_id else None
        if dataset and dataset.record_count is not None:
            expected_run_count = dataset.record_count
        else:
            try:
                expected_run_count = sum(1 for _ in _records(Path(snap.storage_path), Path(snap.storage_path).suffix.lstrip(".")))
            except Exception:
                expected_run_count = total

    return {
        "items": [run_out(x) for x in items],
        "offset": actual_offset,
        "limit": actual_limit,
        "total": total,
        "has_more": has_more,
        "next_offset": next_offset,
        "total_persisted_runs": total,
        "expected_run_count": expected_run_count,
    }

# ---------------------------------------------------------------------------
# Repetitions APIs (rerun, history, specific runs/results, evaluation, export)
# ---------------------------------------------------------------------------

@router.post("/experiments/{experiment_id}/rerun", status_code=201)
@router.post("/experiments/{experiment_id}/repetitions", status_code=201)
def rerun_experiment(
    experiment_id: str,
    request: Request,
    body: ExperimentRerunRequest | None = None,
    db: Session = Depends(get_db),
):
    exp = db.get(Experiment, experiment_id)
    if not exp:
        missing("Experiment")
    idempotency_key = (body.idempotency_key if body else None) or request.headers.get("x-idempotency-key") or request.headers.get("idempotency-key")
    try:
        rep = create_repetition(db=db, exp=exp, idempotency_key=idempotency_key, db_factory=SessionLocal)
    except ValueError as exc:
        raise HTTPException(409, detail={"code": "EXPERIMENT_STILL_RUNNING", "message": str(exc)})
    return {
        "id": rep.id,
        "repetition_id": rep.id,
        "experiment_id": exp.id,
        "repetition_index": rep.repetition_index,
        "status": rep.status,
        "run_count": rep.run_count,
        "completed_run_count": rep.completed_run_count,
        "failed_run_count": rep.failed_run_count,
        "evaluation_id": rep.evaluation_id,
        "idempotency_key": rep.idempotency_key,
        "created_at": rep.created_at,
        "started_at": rep.started_at,
        "completed_at": rep.completed_at,
        "experiment": exp_out(exp),
        "repetition": repetition_out(rep, db),
        "message": f"Repetition {rep.repetition_index} started successfully",
    }

@router.get("/experiments/{experiment_id}/repetitions")
def list_experiment_repetitions(experiment_id: str, db: Session = Depends(get_db)):
    exp = db.get(Experiment, experiment_id)
    if not exp:
        missing("Experiment")
    reps = grouping_service.get_experiment_repetitions(db, experiment_id)
    return {
        "items": reps,
        "total": len(reps),
        "experiment_id": experiment_id,
    }

def _get_repetition_or_404(db: Session, experiment_id: str, rep_id_or_idx: str) -> ExperimentRepetition:
    rep = None
    if rep_id_or_idx.isdigit():
        idx = int(rep_id_or_idx)
        rep = db.query(ExperimentRepetition).filter_by(experiment_id=experiment_id, repetition_index=idx).first()
    else:
        rep = db.get(ExperimentRepetition, rep_id_or_idx)
    if not rep or rep.experiment_id != experiment_id:
        missing("Experiment repetition")
    return rep

@router.get("/experiments/{experiment_id}/repetitions/{repetition_id_or_index}")
def get_experiment_repetition(experiment_id: str, repetition_id_or_index: str, db: Session = Depends(get_db)):
    exp = db.get(Experiment, experiment_id)
    if not exp:
        missing("Experiment")
    rep = _get_repetition_or_404(db, experiment_id, repetition_id_or_index)
    return repetition_out(rep, db)

@router.get("/experiments/{experiment_id}/repetitions/{repetition_id_or_index}/runs")
def repetition_runs(
    experiment_id: str,
    repetition_id_or_index: str,
    offset: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=settings.max_page_size),
    db: Session = Depends(get_db),
):
    exp = db.get(Experiment, experiment_id)
    if not exp:
        missing("Experiment")
    rep = _get_repetition_or_404(db, experiment_id, repetition_id_or_index)
    query = db.query(Run).filter_by(experiment_id=experiment_id, repetition_id=rep.id).order_by(Run.record_index)
    total = query.count()
    items = query.offset(offset).limit(limit).all()
    has_more = (offset + len(items)) < total
    next_offset = (offset + len(items)) if has_more else None
    return {
        "items": [run_out(x) for x in items],
        "offset": offset,
        "limit": limit,
        "total": total,
        "has_more": has_more,
        "next_offset": next_offset,
        "total_persisted_runs": total,
        "expected_run_count": rep.run_count or total,
        "repetition_id": rep.id,
        "repetition_index": rep.repetition_index,
    }

@router.get("/experiments/{experiment_id}/repetitions/{repetition_id_or_index}/results")
def repetition_results(
    experiment_id: str,
    repetition_id_or_index: str,
    offset: int = Query(0, ge=0),
    limit: int | None = Query(None, ge=1, le=settings.max_page_size),
    all: bool = Query(False),
    db: Session = Depends(get_db),
):
    exp = db.get(Experiment, experiment_id)
    if not exp:
        missing("Experiment")
    rep = _get_repetition_or_404(db, experiment_id, repetition_id_or_index)
    query = db.query(Run).filter_by(experiment_id=experiment_id, repetition_id=rep.id).order_by(Run.record_index)
    total = query.count()
    if all or limit is None:
        items = query.all()
        actual_offset = 0
        actual_limit = total
        has_more = False
        next_offset = None
    else:
        items = query.offset(offset).limit(limit).all()
        actual_offset = offset
        actual_limit = limit
        has_more = (offset + len(items)) < total
        next_offset = (offset + len(items)) if has_more else None
    return {
        "items": [run_out(x) for x in items],
        "offset": actual_offset,
        "limit": actual_limit,
        "total": total,
        "has_more": has_more,
        "next_offset": next_offset,
        "total_persisted_runs": total,
        "expected_run_count": rep.run_count or total,
        "repetition_id": rep.id,
        "repetition_index": rep.repetition_index,
    }

@router.post("/experiments/{experiment_id}/repetitions/{repetition_id_or_index}/evaluations", status_code=201)
def evaluate_repetition_endpoint(
    experiment_id: str,
    repetition_id_or_index: str,
    body: EvaluationCreate | None = None,
    db: Session = Depends(get_db),
):
    exp = db.get(Experiment, experiment_id)
    if not exp:
        missing("Experiment")
    rep = _get_repetition_or_404(db, experiment_id, repetition_id_or_index)
    force = (body or EvaluationCreate()).force
    is_ready, err_code, err_msg = evaluation_service.check_evaluation_readiness(db, exp, repetition_id=rep.id)
    if not is_ready:
        if err_code == "EVALUATION_ALREADY_RUNNING" and force:
            pass
        else:
            status_code = 422 if err_code == "SNAPSHOT_MISSING" else 409
            raise HTTPException(status_code, detail={"code": err_code, "message": err_msg})
    try:
        item = evaluation_service.evaluate_experiment(db, exp, force=force, repetition_id=rep.id)
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise HTTPException(422, detail={"code": "EVALUATION_ERROR", "message": str(exc)})
    return evaluation_service.evaluation_out(item)

@router.get("/experiments/{experiment_id}/repetitions/{repetition_id_or_index}/evaluation")
def get_repetition_evaluation_endpoint(
    experiment_id: str,
    repetition_id_or_index: str,
    db: Session = Depends(get_db),
):
    exp = db.get(Experiment, experiment_id)
    if not exp:
        missing("Experiment")
    rep = _get_repetition_or_404(db, experiment_id, repetition_id_or_index)
    ev = None
    if rep.evaluation_id:
        ev = db.get(Evaluation, rep.evaluation_id)
    if not ev:
        ev = db.query(Evaluation).filter_by(experiment_id=exp.id, repetition_id=rep.id, status="completed").order_by(Evaluation.created_at.desc()).first()
    if not ev:
        raise HTTPException(404, detail={"code": "EVALUATION_NOT_FOUND", "message": f"No completed evaluation for repetition {rep.repetition_index}"})
    return evaluation_service.evaluation_out(ev, include_runs=True, db=db)

@router.get("/experiments/{experiment_id}/repetitions/exports/{format}")
def export_repetitions_list(experiment_id: str, format: str, db: Session = Depends(get_db)):
    exp = db.get(Experiment, experiment_id)
    if not exp:
        missing("Experiment")
    if format not in {"jsonl", "csv"}:
        raise HTTPException(415, detail={"code": "UNSUPPORTED_EXPORT_FORMAT", "message": "Supported formats: jsonl, csv"})
    reps = grouping_service.get_experiment_repetitions(db, experiment_id)
    if format == "jsonl":
        content = "".join(json.dumps(r, default=str) + "\n" for r in reps)
        media = "application/x-ndjson"
    else:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["repetition_id", "experiment_id", "repetition_index", "status", "run_count", "completed_run_count", "failed_run_count", "evaluation_id", "created_at", "started_at", "completed_at"])
        for r in reps:
            writer.writerow([r.get("id"), r.get("experiment_id"), r.get("repetition_index"), r.get("status"), r.get("run_count"), r.get("completed_run_count"), r.get("failed_run_count"), r.get("evaluation_id"), r.get("created_at"), r.get("started_at"), r.get("completed_at")])
        content = buf.getvalue()
        media = "text/csv"
    return StreamingResponse(iter([content]), media_type=media, headers={"Content-Disposition": f'attachment; filename="{experiment_id}_repetitions.{format}"'})

@router.get("/experiments/{experiment_id}/repetitions/{repetition_id_or_index}/exports/{format}")
def export_single_repetition_runs(experiment_id: str, repetition_id_or_index: str, format: str, db: Session = Depends(get_db)):
    exp = db.get(Experiment, experiment_id)
    if not exp:
        missing("Experiment")
    rep = _get_repetition_or_404(db, experiment_id, repetition_id_or_index)
    if format not in {"jsonl", "csv"}:
        raise HTTPException(415, detail={"code": "UNSUPPORTED_EXPORT_FORMAT", "message": "Supported formats: jsonl, csv"})
    runs = db.query(Run).filter_by(experiment_id=experiment_id, repetition_id=rep.id).order_by(Run.record_index).all()
    if format == "jsonl":
        content = "".join(json.dumps(run_out(r), default=str) + "\n" for r in runs)
        media = "application/x-ndjson"
    else:
        buf = io.StringIO()
        writer = csv.writer(buf)
        writer.writerow(["run_id", "repetition_id", "repetition_index", "record_index", "status", "execution_duration_ms", "output", "error"])
        for r in runs:
            writer.writerow([r.id, rep.id, rep.repetition_index, r.record_index, r.status, r.execution_duration_ms, json.dumps(r.output), json.dumps(r.error)])
        content = buf.getvalue()
        media = "text/csv"
    return StreamingResponse(iter([content]), media_type=media, headers={"Content-Disposition": f'attachment; filename="{experiment_id}_rep{rep.repetition_index}.{format}"'})

# ---------------------------------------------------------------------------
# Experiment Groups APIs (Baseline vs EGAL grouping, comparisons, exports)
# ---------------------------------------------------------------------------

@router.post("/experiment-groups", status_code=201)
@router.post("/experiments/groups", status_code=201)
def create_experiment_group_endpoint(body: ExperimentGroupCreate, db: Session = Depends(get_db)):
    return grouping_service.create_experiment_group_service(db, body, db_factory=SessionLocal)

@router.post("/experiment-groups/link", status_code=200)
@router.post("/experiments/groups/link", status_code=200)
def link_experiment_group_endpoint(body: ExperimentGroupLink, db: Session = Depends(get_db)):
    return grouping_service.link_experiments_to_group_service(db, body)

@router.get("/experiment-groups")
@router.get("/experiments/groups")
def list_experiment_groups_endpoint(db: Session = Depends(get_db)):
    return {"items": grouping_service.list_groups_service(db)}

@router.get("/experiment-groups/{group_id}")
@router.get("/experiments/groups/{group_id}")
def get_experiment_group_endpoint(group_id: str, db: Session = Depends(get_db)):
    return grouping_service.get_group_detail_service(db, group_id)

@router.get("/experiment-groups/{group_id}/exports/{format}")
@router.get("/experiments/groups/{group_id}/exports/{format}")
def export_experiment_group_endpoint(group_id: str, format: str, db: Session = Depends(get_db)):
    content, media, filename = grouping_service.export_group_service(db, group_id, format)
    return StreamingResponse(
        iter([content]),
        media_type=media,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

@router.post("/experiments/{experiment_id}/evaluations",status_code=201)
def create_evaluation(
    experiment_id: str,
    body: EvaluationCreate | None = None,
    repetition_id: str | None = None,
    repetition_index: int | None = None,
    db: Session = Depends(get_db),
):
    if not isinstance(repetition_id, str): repetition_id = None
    if not isinstance(repetition_index, int): repetition_index = None
    experiment = db.get(Experiment, experiment_id)
    if not experiment: missing("Experiment")
    target_rep_id = (body.repetition_id if body else None) or repetition_id
    target_rep_idx = (body.repetition_index if body else None) or repetition_index
    is_ready, err_code, err_msg = evaluation_service.check_evaluation_readiness(
        db, experiment, repetition_id=target_rep_id, repetition_index=target_rep_idx
    )
    force = (body or EvaluationCreate()).force
    if not is_ready:
        if err_code == "EVALUATION_ALREADY_RUNNING" and force:
            pass
        else:
            status_code = 422 if err_code == "SNAPSHOT_MISSING" else 409
            raise HTTPException(status_code, detail={"code": err_code, "message": err_msg})
    try:
        item = evaluation_service.evaluate_experiment(
            db, experiment, force=force, repetition_id=target_rep_id, repetition_index=target_rep_idx
        )
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        raise HTTPException(422, detail={"code": "EVALUATION_ERROR", "message": str(exc)})
    return evaluation_service.evaluation_out(item)

@router.get("/experiments/{experiment_id}/evaluations")
def list_evaluations(
    experiment_id: str,
    repetition_id: str | None = None,
    repetition_index: int | None = None,
    db: Session = Depends(get_db),
):
    if not isinstance(repetition_id, str): repetition_id = None
    if not isinstance(repetition_index, int): repetition_index = None
    if not db.get(Experiment, experiment_id): missing("Experiment")
    query = db.query(Evaluation).filter_by(experiment_id=experiment_id)
    if repetition_id:
        query = query.filter(Evaluation.repetition_id == repetition_id)
    elif repetition_index is not None:
        query = query.filter(Evaluation.repetition_index == repetition_index)
    return {"items": [evaluation_service.evaluation_out(x) for x in query.order_by(Evaluation.created_at.desc()).all()]}

@router.get("/experiments/{experiment_id}/evaluations/{evaluation_id}")
def get_evaluation(experiment_id:str,evaluation_id:str,db:Session=Depends(get_db)):
    item=db.get(Evaluation,evaluation_id)
    if not item or item.experiment_id!=experiment_id: missing("Evaluation")
    return evaluation_service.evaluation_out(item,True,db)

@router.get("/experiments/{experiment_id}/evaluations/{evaluation_id}/runs/{run_id}")
def get_run_evaluation(experiment_id:str,evaluation_id:str,run_id:str,db:Session=Depends(get_db)):
    item=db.get(Evaluation,evaluation_id)
    if not item or item.experiment_id!=experiment_id: missing("Evaluation")
    result=db.query(RunEvaluation).filter_by(evaluation_id=evaluation_id,run_id=run_id).first()
    if not result: missing("Run evaluation")
    return evaluation_service._out(result)

@router.get("/experiments/{experiment_id}/evaluations/{evaluation_id}/exports/{format}")
def export_evaluation(experiment_id:str,evaluation_id:str,format:str,db:Session=Depends(get_db)):
    item=db.get(Evaluation,evaluation_id)
    if not item or item.experiment_id!=experiment_id: missing("Evaluation")
    if format not in {"jsonl","csv"}: raise HTTPException(415,detail={"code":"UNSUPPORTED_EXPORT_FORMAT","message":"Supported formats: jsonl, csv"})
    rows=[evaluation_service._out(x) for x in db.query(RunEvaluation).filter_by(evaluation_id=evaluation_id).order_by(RunEvaluation.scenario_id,RunEvaluation.run_id)]
    if format=="jsonl":
        content=json.dumps({"evaluation":evaluation_service.evaluation_out(item),"record_type":"evaluation_summary"},default=str)+"\n"+"".join(json.dumps({"record_type":"run_evaluation",**row},default=str)+"\n" for row in rows); media="application/x-ndjson"
    else:
        buf=io.StringIO(); writer=csv.writer(buf); writer.writerow(["evaluation_id","run_id","scenario_id","category","execution_status","output_schema_valid","task_completion","unsupported_action","recovery","review_required","claim_assessments","warnings","exclusions"])
        for row in rows: writer.writerow([evaluation_id,row["run_id"],row["scenario_id"],row["category"],row["execution_status"],row["output_schema_valid"],json.dumps(row["task_completion"]),json.dumps(row["unsupported_action"]),json.dumps(row["recovery"]),row["review_required"],json.dumps(row["claim_assessments"]),json.dumps(row["warnings"]),json.dumps(row["exclusions"])] )
        content=buf.getvalue(); media="text/csv"
    return StreamingResponse(iter([content]),media_type=media,headers={"Content-Disposition":f'attachment; filename="{evaluation_id}.{format}"'})

@router.get("/evaluations")
def list_all_evaluations(db:Session=Depends(get_db)):
    return {"items":[evaluation_service.evaluation_out(x) for x in db.query(Evaluation).order_by(Evaluation.created_at.desc()).all()]}

@router.get("/experiments/{experiment_id}/metrics")
def metrics(
    experiment_id: str,
    repetition_id: str | None = None,
    repetition_index: int | None = None,
    db: Session = Depends(get_db),
):
    if not isinstance(repetition_id, str): repetition_id = None
    if not isinstance(repetition_index, int): repetition_index = None
    if not db.get(Experiment, experiment_id): missing("Experiment")
    query = db.query(Evaluation).filter_by(experiment_id=experiment_id, status="completed")
    if repetition_id:
        query = query.filter(Evaluation.repetition_id == repetition_id)
    elif repetition_index is not None:
        query = query.filter(Evaluation.repetition_index == repetition_index)
    item = query.order_by(Evaluation.created_at.desc()).first()
    if not item: raise HTTPException(409, detail={"code": "EVALUATION_NOT_RUN", "message": "No completed evaluation exists for this experiment"})
    return {"evaluation_id": item.id, "status": item.status, "metrics": item.metrics, "manifest": item.manifest}

@router.post("/experiments/{experiment_id}/{action}")
def control_experiment(experiment_id:str,action:Literal["pause","resume","stop"],db:Session=Depends(get_db)):
    e=db.get(Experiment,experiment_id)
    if not e: missing("Experiment")
    expected={"pause":"running","resume":"paused","stop":"running"}
    if action not in expected or e.status!=expected[action]: raise HTTPException(409,detail={"code":"INVALID_EXPERIMENT_STATE","message":"Action is invalid for current experiment state"})
    e.status={"pause":"paused","resume":"starting","stop":"stopped"}[action]; db.commit()
    if action=="resume": start(SessionLocal,e.id)
    return exp_out(e)
@router.get("/experiments/{experiment_id}/manifest")
def manifest(experiment_id:str,db:Session=Depends(get_db)):
    e=db.get(Experiment,experiment_id)
    if not e: missing("Experiment")
    s=db.get(DatasetSnapshot,e.dataset_snapshot_id); agent=resolve_agent(db,e.agent_id); latest=db.query(Evaluation).filter_by(experiment_id=e.id,status="completed").order_by(Evaluation.created_at.desc()).first(); return {"experiment":exp_out(e),"dataset_snapshot":{"id":s.id,"fingerprint":s.fingerprint},"agent":agent.metadata() if agent else {"id":e.agent_id,"status":"retired_or_unavailable"},"provider":e.provider_metadata_snapshot or (providers[e.provider_id].metadata() if e.provider_id in providers else {"id":e.provider_id,"status":"deleted_or_unavailable"}),"evaluation":evaluation_service.evaluation_out(latest) if latest else {"status":"not_run"}}
@router.get("/experiments/{experiment_id}/exports/{format}")
def export(experiment_id:str,format:str,db:Session=Depends(get_db)):
    if format not in {"jsonl","csv"}: raise HTTPException(415,detail={"code":"UNSUPPORTED_EXPORT_FORMAT","message":"Supported formats: jsonl, csv"})
    items=db.query(Run).filter_by(experiment_id=experiment_id).all()
    if format=="jsonl": content="".join(json.dumps(run_out(r),default=str)+"\n" for r in items); media="application/x-ndjson"
    else:
        buf=io.StringIO(); w=csv.writer(buf); w.writerow(["run_id","record_index","status","output","error"]); [w.writerow([r.id,r.record_index,r.status,json.dumps(r.output),json.dumps(r.error)]) for r in items]; content=buf.getvalue(); media="text/csv"
    return StreamingResponse(iter([content]),media_type=media,headers={"Content-Disposition":f'attachment; filename="{experiment_id}.{format}"'})

@router.get("/analysis/options", response_model=AnalysisOptionsResponse)
def get_analysis_options_endpoint(db: Session = Depends(get_db)):
    return analysis_service.get_analysis_options(db)

@router.post("/analysis/report", response_model=AnalysisReportResponse)
def get_analysis_report_endpoint(body: AnalysisFilterRequest, db: Session = Depends(get_db)):
    return analysis_service.generate_analysis_report(db, body)



