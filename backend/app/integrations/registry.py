"""Trusted adapters. Persistent registrations never execute user-provided code."""
from abc import ABC, abstractmethod
import ipaddress, json, socket, time
from urllib.parse import urlparse
from urllib.request import Request, build_opener, HTTPErrorProcessor
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field
from app.core.config import settings
from app.models.entities import AgentRegistration

class ExecutionResult(BaseModel):
    agent_id: str; run_status: str
    raw_output: dict | str | None = None; normalized_output: dict | None = None
    execution_duration_ms: int = 0; error_code: str | None = None; error_message: str | None = None
    metadata: dict = Field(default_factory=dict)
class AgentAdapter(ABC):
    id: str
    @abstractmethod
    def metadata(self) -> dict: ...
    def get_capabilities(self): return self.metadata().get("capabilities", [])
    def validate_configuration(self, config): return []
    def validate_input(self, payload): return []
    def health_check(self, config=None): return {"ok": True}
    @abstractmethod
    def run(self, payload, provider, configuration=None) -> ExecutionResult: ...
class Provider(ABC):
    id: str
    @abstractmethod
    def metadata(self) -> dict: ...
    @abstractmethod
    def complete(self, payload): ...
class MockProvider(Provider):
    id="mock"
    def metadata(self): return {"id":self.id,"name":"Deterministic Mock Provider","ready":True,"mock":True,"models":["mock-v1"]}
    def complete(self,payload):
        if payload.get("__simulate_error"): raise RuntimeError("simulated provider error")
        return {"model":"mock-v1","content":f"mock response for {sorted(payload)}"}
class MockAgent(AgentAdapter):
    id="mock-agent"
    def metadata(self): return {"id":self.id,"name":"Deterministic Mock Agent","agent_type":"built_in","adapter_type":"mock","version":"1","ready":True,"mock":True,"capabilities":["structured_input","structured_output","supports_health_check"]}
    def run(self,payload,provider,configuration=None):
        started=time.monotonic(); raw=provider.complete(payload) if provider else {"content":"mock response"}
        normalized={"agent":self.id,"response":raw,"received_fields":sorted(payload)}
        return ExecutionResult(agent_id=self.id,run_status="completed",raw_output=raw,normalized_output=normalized,execution_duration_ms=int((time.monotonic()-started)*1000))
class ML4FinancialNewsStub(AgentAdapter):
    id="ml4financialnews"
    def metadata(self): return {"id":self.id,"name":"ML4FinancialNews","agent_type":"built_in","version":"unknown","ready":False,"status":"stub","reason":"Integration and baseline verification are scheduled for Phase 4."}
    def run(self,payload,provider,configuration=None): raise NotImplementedError(self.metadata()["reason"])

def schema_errors(schema, value, label):
    return [] if not schema else [f"{label}: {e.message}" for e in Draft202012Validator(schema).iter_errors(value)]
def registration_metadata(item, ready=None):
    return {"id":item.id,"name":item.display_name,"description":item.description,"agent_type":item.agent_type,"adapter_type":item.adapter_type,"version":item.version,"input_schema":item.input_schema,"output_schema":item.output_schema,"configuration_schema":item.configuration_schema,"capabilities":item.capabilities,"status":item.status,"ready":item.status=="ready" if ready is None else ready,"created_at":item.created_at,"updated_at":item.updated_at}
class RegisteredMockAdapter(MockAgent):
    def __init__(self,item): self.item=item; self.id=item.id
    def metadata(self): return registration_metadata(self.item)
    def validate_configuration(self,c): return schema_errors(self.item.configuration_schema,c,"configuration")
    def validate_input(self,p): return schema_errors(self.item.input_schema,p,"input")
    def run(self,payload,provider,configuration=None):
        result=super().run(payload,provider,configuration); result.agent_id=self.id; result.normalized_output["agent"]=self.id
        errors=schema_errors(self.item.output_schema,result.normalized_output,"output")
        if errors: result.run_status="failed"; result.error_code="OUTPUT_SCHEMA_INVALID"; result.error_message="; ".join(errors)
        return result
class NoRedirect(HTTPErrorProcessor):
    def http_response(self,request,response): return response
    https_response=http_response
def safe_endpoint(endpoint):
    parsed=urlparse(endpoint)
    if parsed.scheme not in {"http","https"} or not parsed.hostname or parsed.username or parsed.password: raise ValueError("endpoint must be an absolute HTTP(S) URL without embedded credentials")
    try: addresses={x[4][0] for x in socket.getaddrinfo(parsed.hostname,parsed.port or (443 if parsed.scheme=="https" else 80),type=socket.SOCK_STREAM)}
    except socket.gaierror as exc: raise ValueError("endpoint hostname cannot be resolved") from exc
    for address in addresses:
        ip=ipaddress.ip_address(address)
        if (ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved) and not settings.allow_local_http_agents: raise ValueError("private, loopback, link-local, and reserved endpoints are blocked")
class HTTPAgentAdapter(AgentAdapter):
    def __init__(self,item): self.item=item; self.id=item.id
    def metadata(self): return registration_metadata(self.item)
    def validate_configuration(self,c):
        errors=schema_errors(self.item.configuration_schema,c,"configuration"); endpoint=(c or self.item.adapter_config).get("endpoint")
        if not endpoint: return errors+["configuration: endpoint is required"]
        try: safe_endpoint(endpoint)
        except ValueError as exc: errors.append(str(exc))
        return errors
    def validate_input(self,p): return schema_errors(self.item.input_schema,p,"input")
    def health_check(self,c=None):
        errors=self.validate_configuration(c or self.item.adapter_config)
        return {"ok":not errors,"errors":errors,"note":"Configuration-only HTTP health check; no endpoint call is assumed."}
    def run(self,payload,provider,configuration=None):
        cfg={**self.item.adapter_config,**(configuration or {})}; errors=self.validate_configuration(cfg); started=time.monotonic()
        if errors: return ExecutionResult(agent_id=self.id,run_status="failed",error_code="AGENT_CONFIGURATION_INVALID",error_message="; ".join(errors))
        try:
            request=Request(cfg["endpoint"],data=json.dumps({"input":payload,"configuration":cfg.get("execution_configuration",{})}).encode(),headers={"Content-Type":"application/json"},method="POST")
            with build_opener(NoRedirect()).open(request,timeout=float(cfg.get("timeout_seconds",settings.http_agent_timeout_seconds))) as response:
                if not 200<=response.status<300: raise RuntimeError(f"HTTP agent returned status {response.status}")
                body=response.read(1024*1024+1)
                if len(body)>1024*1024: raise RuntimeError("HTTP agent response exceeds 1 MiB limit")
            raw=json.loads(body.decode()); normalized=raw.get("output",raw) if isinstance(raw,dict) else None
            if not isinstance(normalized,dict): raise ValueError("HTTP agent response must be a JSON object or contain an object output")
            errors=schema_errors(self.item.output_schema,normalized,"output")
            if errors: return ExecutionResult(agent_id=self.id,run_status="failed",raw_output=raw,error_code="OUTPUT_SCHEMA_INVALID",error_message="; ".join(errors),execution_duration_ms=int((time.monotonic()-started)*1000))
            return ExecutionResult(agent_id=self.id,run_status="completed",raw_output=raw,normalized_output=normalized,execution_duration_ms=int((time.monotonic()-started)*1000))
        except Exception as exc: return ExecutionResult(agent_id=self.id,run_status="failed",error_code="HTTP_AGENT_FAILED",error_message=str(exc),execution_duration_ms=int((time.monotonic()-started)*1000))

agents={a.id:a for a in (MockAgent(),ML4FinancialNewsStub())}; providers={p.id:p for p in (MockProvider(),)}
SUPPORTED_CUSTOM_ADAPTERS={"mock":RegisteredMockAdapter,"http":HTTPAgentAdapter}
def resolve_agent(db,agent_id):
    if agent_id == "financial_news_analysis":
        from app.integrations.financial_news import FinancialNewsAnalysisAgent
        return FinancialNewsAnalysisAgent(db)
    if agent_id == "financial_news_analysis_egal":
        from app.integrations.financial_news import FinancialNewsEgalAgent
        return FinancialNewsEgalAgent(db)
    if agent_id in agents: return agents[agent_id]
    item=db.get(AgentRegistration,agent_id)
    if not item or item.status == "retired": return None
    adapter=SUPPORTED_CUSTOM_ADAPTERS.get(item.adapter_type)
    return adapter(item) if adapter else None
def list_agent_metadata(db):
    from app.integrations.financial_news import FinancialNewsAnalysisAgent, FinancialNewsEgalAgent
    return [a.metadata() for a in agents.values()]+[FinancialNewsAnalysisAgent(db).metadata(), FinancialNewsEgalAgent(db).metadata()]+[registration_metadata(x) for x in db.query(AgentRegistration).filter(AgentRegistration.status!="retired").order_by(AgentRegistration.created_at).all()]
