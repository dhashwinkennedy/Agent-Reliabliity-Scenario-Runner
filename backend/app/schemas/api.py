from pydantic import BaseModel, Field, model_validator
from typing import Any, Literal
class ExperimentCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    dataset_snapshot_id: str
    agent_id: str
    provider_id: str
    model: str | None = Field(default=None, max_length=255, description="Model override for the experiment execution")
    input_mapping: dict[str, str] = Field(default_factory=dict, description="Dataset source field to agent payload field")
    agent_configuration: dict[str, Any] = Field(default_factory=dict)
    group_id: str | None = Field(default=None, max_length=100, description="Optional experiment-group identifier")
    group_name: str | None = Field(default=None, max_length=255, description="Optional shared experiment name")

class AgentRegistrationCreate(BaseModel):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,99}$")
    display_name: str = Field(min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    agent_type: Literal["custom_python", "external_http"]
    adapter_type: Literal["mock", "http"]
    version: str = Field(default="unknown", max_length=100)
    input_schema: dict | None = None
    output_schema: dict | None = None
    configuration_schema: dict | None = None
    adapter_config: dict[str, Any] = Field(default_factory=dict)
    capabilities: list[str] = Field(default_factory=list)
class AgentRegistrationUpdate(BaseModel):
    display_name: str | None = Field(default=None, min_length=1, max_length=255)
    description: str | None = Field(default=None, max_length=4000)
    version: str | None = Field(default=None, max_length=100)
    input_schema: dict | None = None
    output_schema: dict | None = None
    configuration_schema: dict | None = None
    adapter_config: dict[str, Any] | None = None
    capabilities: list[str] | None = None
class AgentTestRequest(BaseModel):
    input: dict[str, Any] = Field(default_factory=dict)
    configuration: dict[str, Any] = Field(default_factory=dict)

class ProviderCreate(BaseModel):
    id: str | None = Field(default=None, pattern=r"^[a-z][a-z0-9-]{2,99}$")
    name: str = Field(min_length=1, max_length=255)
    provider_type: Literal["openai_compatible"]
    base_url: str = Field(min_length=8, max_length=1000)
    default_model: str = Field(min_length=1, max_length=255)
    api_key: str | None = Field(default=None, max_length=10000)
    timeout_seconds: float = Field(default=30, gt=0)
    is_active: bool = True
    generation_parameters: dict[str, Any] = Field(default_factory=dict)

class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    base_url: str | None = Field(default=None, min_length=8, max_length=1000)
    default_model: str | None = Field(default=None, min_length=1, max_length=255)
    api_key: str | None = Field(default=None, max_length=10000)
    clear_api_key: bool = False
    timeout_seconds: float | None = Field(default=None, gt=0)
    is_active: bool | None = None
    generation_parameters: dict[str, Any] | None = None

class EvaluationCreate(BaseModel):
    force: bool = False
    repetition_id: str | None = Field(default=None, description="Optional target repetition ID")
    repetition_index: int | None = Field(default=None, description="Optional target repetition index")

class ExperimentRerunRequest(BaseModel):
    idempotency_key: str | None = Field(default=None, max_length=100, description="Client token for idempotent execution")

class ExperimentGroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255, description="Human-readable shared experiment name")
    group_id: str | None = Field(default=None, max_length=100, description="Stable experiment group identifier")
    dataset_snapshot_id: str
    provider_id: str
    model: str | None = Field(default=None, max_length=255)
    input_mapping: dict[str, str] = Field(default_factory=dict)
    baseline_configuration: dict[str, Any] = Field(default_factory=dict)
    egal_configuration: dict[str, Any] = Field(default_factory=dict)
    auto_start: bool = False

class ExperimentGroupLink(BaseModel):
    group_name: str = Field(default="", max_length=255)
    group_id: str | None = Field(default=None, max_length=100)
    experiment_ids: list[str] = Field(default_factory=list)
    baseline_experiment_id: str | None = None
    egal_experiment_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def populate_and_normalize(cls, data: Any) -> Any:
        if isinstance(data, dict):
            # If experiment_ids is missing or empty, populate from baseline/egal IDs
            eids = data.get("experiment_ids")
            if not eids:
                b_id = data.get("baseline_experiment_id")
                e_id = data.get("egal_experiment_id")
                if b_id and e_id:
                    data["experiment_ids"] = [b_id, e_id]
            # If group_name is missing, try name or group_id
            if not data.get("group_name"):
                data["group_name"] = data.get("name") or data.get("group_id") or ""
        return data

    @model_validator(mode="after")
    def validate_link_contract(self) -> "ExperimentGroupLink":
        if len(self.experiment_ids) < 2:
            raise ValueError("At least 2 experiment_ids are required to form a comparison group")
        if not self.group_name or len(self.group_name.strip()) == 0:
            raise ValueError("group_name must not be empty")
        return self

class ConsistencyAggregationCreate(BaseModel):
    evaluation_ids: list[str] = Field(default_factory=list, description="IDs of evaluations to aggregate across")

