from pydantic import BaseModel, Field
from typing import Any, Literal

class AnalysisFilterRequest(BaseModel):
    dataset_snapshot_id: str
    model_name: str | None = None
    provider_id: str | None = None
    agent_ids: list[str] = Field(default_factory=list)
    experiment_ids: list[str] = Field(default_factory=list)

class AnalysisOptionsResponse(BaseModel):
    datasets: list[dict[str, Any]]
    dataset_snapshots: list[dict[str, Any]]
    providers: list[dict[str, Any]]
    models: list[str]
    agents: list[dict[str, Any]]
    experiments: list[dict[str, Any]]
    conditions: list[str]

class MetricDelta(BaseModel):
    value: float | None = None
    direction: Literal["improved", "regressed", "unchanged", "not_assessable"]
    interpretation: Literal["higher_is_better", "lower_is_better"]

class BaselineVsEgalItem(BaseModel):
    model: str
    provider: str
    baseline: dict[str, Any]
    egal: dict[str, Any]
    delta: dict[str, MetricDelta]

class BaselineVsEgalComparison(BaseModel):
    available: bool
    comparisons: list[BaselineVsEgalItem]

class AnalysisReportResponse(BaseModel):
    report_metadata: dict[str, Any]
    dataset: dict[str, Any]
    coverage: dict[str, Any]
    summary: dict[str, Any]
    primary_metrics: dict[str, Any]
    category_breakdown: list[dict[str, Any]]
    scenario_breakdown: list[dict[str, Any]]
    model_comparison: list[dict[str, Any]]
    baseline_vs_egal: dict[str, Any]
    recommendation_distribution: list[dict[str, Any]]
    egal_analysis: dict[str, Any]
    charts: dict[str, Any]
    research_metadata: dict[str, Any]
