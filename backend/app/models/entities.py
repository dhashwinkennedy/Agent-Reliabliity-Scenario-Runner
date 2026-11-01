from datetime import datetime
from sqlalchemy import String, Integer, DateTime, Text, ForeignKey, JSON, Boolean, Index, Float
from sqlalchemy.orm import Mapped, mapped_column
from app.database.base import Base

def now(): return datetime.utcnow()
class Dataset(Base):
    __tablename__ = "datasets"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    original_filename: Mapped[str] = mapped_column(String(255))
    format: Mapped[str] = mapped_column(String(10))
    size_bytes: Mapped[int] = mapped_column(Integer)
    record_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    storage_path: Mapped[str] = mapped_column(String(500), unique=True)
    validation_status: Mapped[str] = mapped_column(String(30), default="pending")
    validation_errors: Mapped[list] = mapped_column(JSON, default=list)
    validation_warnings: Mapped[list] = mapped_column(JSON, default=list)
    declared_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
class DatasetSnapshot(Base):
    __tablename__ = "dataset_snapshots"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    dataset_id: Mapped[str] = mapped_column(ForeignKey("datasets.id"), index=True)
    fingerprint: Mapped[str] = mapped_column(String(64))
    storage_path: Mapped[str] = mapped_column(String(500), unique=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
class ExperimentGroup(Base):
    __tablename__ = "experiment_groups"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    dataset_snapshot_id: Mapped[str] = mapped_column(ForeignKey("dataset_snapshots.id"), index=True)
    provider_id: Mapped[str] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class Experiment(Base):
    __tablename__ = "experiments"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    group_id: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    group_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    dataset_snapshot_id: Mapped[str] = mapped_column(ForeignKey("dataset_snapshots.id"))
    agent_id: Mapped[str] = mapped_column(String(100))
    provider_id: Mapped[str] = mapped_column(String(100))
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    input_mapping: Mapped[dict] = mapped_column(JSON, default=dict)
    agent_version: Mapped[str | None] = mapped_column(String(100), nullable=True)
    agent_configuration_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    provider_metadata_snapshot: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(30), default="draft", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)

class ExperimentRepetition(Base):
    __tablename__ = "experiment_repetitions"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    repetition_index: Mapped[int] = mapped_column(Integer, default=1, index=True)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    idempotency_key: Mapped[str | None] = mapped_column(String(100), nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    run_count: Mapped[int] = mapped_column(Integer, default=0)
    completed_run_count: Mapped[int] = mapped_column(Integer, default=0)
    failed_run_count: Mapped[int] = mapped_column(Integer, default=0)
    evaluation_id: Mapped[str | None] = mapped_column(String(40), nullable=True, index=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    __table_args__ = (Index("ix_exp_rep_exp_idx", "experiment_id", "repetition_index"),)

class Run(Base):
    __tablename__ = "runs"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    repetition_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("experiment_repetitions.id"), nullable=True, index=True)
    repetition_index: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1, index=True)
    record_index: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(30), default="queued", index=True)
    output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    raw_output: Mapped[dict | str | None] = mapped_column(JSON, nullable=True)
    normalized_output: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    execution_duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    __table_args__ = (Index("ix_runs_experiment_record", "experiment_id", "record_index"),)

class AgentRegistration(Base):
    __tablename__ = "agent_registrations"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    agent_type: Mapped[str] = mapped_column(String(30))
    adapter_type: Mapped[str] = mapped_column(String(30), index=True)
    version: Mapped[str] = mapped_column(String(100), default="unknown")
    input_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    output_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    configuration_schema: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    adapter_config: Mapped[dict] = mapped_column(JSON, default=dict)
    capabilities: Mapped[list] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String(30), default="registered", index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

class ProviderConfiguration(Base):
    __tablename__ = "provider_configurations"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(255))
    provider_type: Mapped[str] = mapped_column(String(50), index=True)
    base_url: Mapped[str] = mapped_column(String(1000))
    model: Mapped[str] = mapped_column(String(255))
    encrypted_api_key: Mapped[str | None] = mapped_column(Text, nullable=True)
    timeout_seconds: Mapped[float] = mapped_column(nullable=False, default=30.0)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    generation_parameters: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    updated_at: Mapped[datetime] = mapped_column(DateTime, default=now, onupdate=now)

class Evaluation(Base):
    __tablename__ = "evaluations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    experiment_id: Mapped[str] = mapped_column(ForeignKey("experiments.id"), index=True)
    repetition_id: Mapped[str | None] = mapped_column(String(40), ForeignKey("experiment_repetitions.id"), nullable=True, index=True)
    repetition_index: Mapped[int | None] = mapped_column(Integer, nullable=True, default=1, index=True)
    dataset_snapshot_id: Mapped[str] = mapped_column(ForeignKey("dataset_snapshots.id"))
    dataset_fingerprint: Mapped[str] = mapped_column(String(64))
    evaluation_schema_version: Mapped[str] = mapped_column(String(30))
    metric_definition_version: Mapped[str] = mapped_column(String(50))
    status: Mapped[str] = mapped_column(String(30), index=True)
    expected_run_count: Mapped[int] = mapped_column(Integer, default=0)
    metrics: Mapped[dict] = mapped_column(JSON, default=dict)
    manifest: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

class RunEvaluation(Base):
    __tablename__ = "run_evaluations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    evaluation_id: Mapped[str] = mapped_column(ForeignKey("evaluations.id"), index=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id"), index=True)
    scenario_id: Mapped[str] = mapped_column(String(100), index=True)
    category: Mapped[str] = mapped_column(String(30), index=True)
    execution_status: Mapped[str] = mapped_column(String(30))
    output_schema_valid: Mapped[bool] = mapped_column(Boolean, default=False)
    task_completion: Mapped[dict] = mapped_column(JSON, default=dict)
    claim_assessments: Mapped[list] = mapped_column(JSON, default=list)
    unsupported_action: Mapped[dict] = mapped_column(JSON, default=dict)
    recovery: Mapped[dict] = mapped_column(JSON, default=dict)
    false_success: Mapped[dict] = mapped_column(JSON, default=dict)
    decision_signature: Mapped[dict] = mapped_column(JSON, default=dict)
    exclusions: Mapped[list] = mapped_column(JSON, default=list)
    warnings: Mapped[list] = mapped_column(JSON, default=list)
    review_required: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)
    __table_args__ = (Index("ix_run_evaluations_evaluation_run", "evaluation_id", "run_id", unique=True),)

class ConsistencyAggregation(Base):
    __tablename__ = "consistency_aggregations"
    id: Mapped[str] = mapped_column(String(40), primary_key=True)
    selected_evaluation_ids: Mapped[list] = mapped_column(JSON, default=list)
    dataset_snapshot_id: Mapped[str] = mapped_column(ForeignKey("dataset_snapshots.id"), index=True)
    dataset_fingerprint: Mapped[str] = mapped_column(String(64), index=True)
    metric_definition_version: Mapped[str] = mapped_column(String(50), default="research-metrics-v1")
    aggregation_status: Mapped[str] = mapped_column(String(30), default="complete", index=True)
    repeatability_scenario_results: Mapped[list] = mapped_column(JSON, default=list)
    consistent_group_count: Mapped[int] = mapped_column(Integer, default=0)
    assessable_group_count: Mapped[int] = mapped_column(Integer, default=0)
    excluded_group_count: Mapped[int] = mapped_column(Integer, default=0)
    coverage: Mapped[float] = mapped_column(Float, default=0.0)
    consistency_rate: Mapped[float | None] = mapped_column(Float, default=None, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=now)



