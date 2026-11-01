"""Versioned contracts for the baseline Financial News Analysis Agent."""
from datetime import datetime
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator

class EvidenceRecord(BaseModel):
    evidence_id: str = Field(min_length=1)
    type: str = Field(min_length=1)
    title: str = Field(min_length=1)
    content: str = Field(min_length=1)
    source_name: str = Field(min_length=1)
    url: str = Field(min_length=1)
    published_at: datetime | None = None

class FinancialNewsInput(BaseModel):
    schema_version: Literal["1.0"]
    scenario_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1, description="Use UNKNOWN when no ticker is available.")
    company_name: str = Field(min_length=1)
    task: str = Field(min_length=1)
    retrieval_mode: Literal["provided_evidence", "tavily_live"] = "provided_evidence"
    search_query: str | None = None
    evidence: list[EvidenceRecord] = Field(default_factory=list)
    ml_forecast: Any | None = None
    @field_validator("evidence")
    @classmethod
    def unique_evidence_ids(cls, value):
        ids=[x.evidence_id for x in value]
        if len(ids) != len(set(ids)): raise ValueError("evidence IDs must be unique")
        return value

class EvidenceLinkedItem(BaseModel):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(default_factory=list)

class FinancialNewsOutput(BaseModel):
    schema_version: Literal["1.0"]
    scenario_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    sentiment: Literal["positive", "neutral", "negative", "mixed", "insufficient_evidence"]
    price_impact: Literal["positive", "neutral", "negative", "mixed", "uncertain"]
    recommendation: Literal["BUY", "HOLD", "SELL"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    forecast_pct: float | None = Field(default=None, allow_inf_nan=False)
    forecast_horizon: Literal["intraday", "short_term", "medium_term", "unspecified"]
    reasoning: list[EvidenceLinkedItem] = Field(default_factory=list)
    key_factors: list[EvidenceLinkedItem] = Field(default_factory=list)
    risk_factors: list[EvidenceLinkedItem] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    source_ids_used: list[str] = Field(default_factory=list)

# EGAL deliberately has a separate contract.  In particular, adding ABSTAIN to
# FinancialNewsOutput would change the baseline agent's public contract.
EgalValidationLabel = Literal[
    "supported_fact", "reasonable_inference", "unsupported_claim",
    "contradiction", "missing_information",
]

class EgalClaimAssessment(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    claim_id: str = Field(min_length=1)
    claim_text: str = Field(min_length=1)
    claim_type: Literal["reasoning", "key_factor", "risk_factor", "numerical_forecast", "recommendation", "missing_information"]
    validation_label: EgalValidationLabel
    evidence_ids: list[str] = Field(default_factory=list)
    explanation: str = Field(min_length=1)
    material: bool
    requires_correction: bool
    contradicted: bool = False

class EgalClaimValidation(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    assessments: list[EgalClaimAssessment] = Field(default_factory=list)

class EgalEvidenceSufficiency(BaseModel):
    schema_version: Literal["1.0"] = "1.0"
    status: Literal["sufficient", "insufficient"]
    material_unsupported_claim_ids: list[str] = Field(default_factory=list)
    material_contradiction_ids: list[str] = Field(default_factory=list)
    critical_missing_information: list[str] = Field(default_factory=list)
    recommendation_adequately_supported: bool
    correction_required: bool
    reason: str = Field(min_length=1)

class EgalAbstentionDecision(BaseModel):
    status: Literal["not_abstained", "abstained"]
    reason_codes: list[str] = Field(default_factory=list)
    reason: str = Field(min_length=1)

class FinancialNewsEgalOutput(BaseModel):
    """EGAL v1 final result.  The nested audit is persisted with the run."""
    schema_version: Literal["1.0"] = "1.0"
    scenario_id: str = Field(min_length=1)
    ticker: str = Field(min_length=1)
    sentiment: Literal["positive", "neutral", "negative", "mixed", "insufficient_evidence"]
    price_impact: Literal["positive", "neutral", "negative", "mixed", "uncertain"]
    recommendation: Literal["BUY", "HOLD", "SELL", "ABSTAIN"]
    confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    forecast_pct: float | None = Field(default=None, allow_inf_nan=False)
    forecast_horizon: Literal["intraday", "short_term", "medium_term", "unspecified"]
    reasoning: list[EvidenceLinkedItem] = Field(default_factory=list)
    key_factors: list[EvidenceLinkedItem] = Field(default_factory=list)
    risk_factors: list[EvidenceLinkedItem] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    source_ids_used: list[str] = Field(default_factory=list)
    abstention: EgalAbstentionDecision
    final_claim_validation: EgalClaimValidation
    final_evidence_sufficiency: EgalEvidenceSufficiency
    audit: dict[str, Any]

class GroundTruth(BaseModel):
    annotation_version: str
    expected_task_completion: bool | None = None
    stance: Literal["positive", "neutral", "negative", "mixed", "insufficient_evidence"] | None = None
    supported_facts: list[EvidenceLinkedItem] = Field(default_factory=list)
    reasonable_inferences: list[EvidenceLinkedItem] = Field(default_factory=list)
    unsupported_claims: list[EvidenceLinkedItem] = Field(default_factory=list)
    contradictions: list[EvidenceLinkedItem] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    expected_abstention: bool | None = None
    annotation_notes: str | None = None

class FinancialNewsDatasetRecord(BaseModel):
    record_schema_version: Literal["1.0"]
    scenario_id: str = Field(min_length=1)
    category: Literal["normal", "ambiguous", "failure"]
    input: FinancialNewsInput
    ground_truth: GroundTruth
    metadata: dict
    @model_validator(mode="after")
    def scenario_consistency(self):
        if self.input.scenario_id != self.scenario_id:
            raise ValueError("input.scenario_id must match scenario_id")
        if self.scenario_id.split("-", 1)[0].lower() != self.category:
            raise ValueError("scenario_id prefix must match category")
        return self
