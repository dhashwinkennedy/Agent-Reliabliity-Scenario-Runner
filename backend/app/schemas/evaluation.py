"""Auditable, versioned evaluator result contracts."""
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field

class ClaimAssessment(BaseModel):
    claim_id: str
    run_id: str
    scenario_id: str
    text: str
    claim_type: str
    evidence_ids: list[str] = Field(default_factory=list)
    assessment_status: str
    assessment_method: str
    reason_codes: list[str] = Field(default_factory=list)
    review_required: bool = False

class RunEvaluationRecord(BaseModel):
    evaluation_schema_version: Literal["1.0"] = "1.0"
    experiment_id: str
    run_id: str
    scenario_id: str
    category: str
    execution_status: str
    output_schema_valid: bool
    task_completion: dict[str, Any]
    claim_assessments: list[ClaimAssessment] = Field(default_factory=list)
    unsupported_action: dict[str, Any]
    recovery: dict[str, Any]
    false_success: dict[str, Any]
    decision_signature: dict[str, Any] = Field(default_factory=dict)
    review_required: bool = False
    exclusions: list[str] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    metric_definition_version: str = "research-metrics-v1"
    dataset_fingerprint: str
    evaluated_at: datetime | None = None

class MetricResult(BaseModel):
    metric_name: str
    metric_version: str
    numerator: int
    denominator: int
    percentage: float | None
    excluded_runs: int
    missing_runs: int
    requires_review: int
    assessment_coverage: float
    status: str
    notes: list[str] = Field(default_factory=list)
    details: dict[str, Any] = Field(default_factory=dict)
