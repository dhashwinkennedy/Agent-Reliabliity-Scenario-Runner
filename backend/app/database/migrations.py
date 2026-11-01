"""Additive development migrations; never delete an existing database."""
from sqlalchemy import inspect, text

def apply_additive_migrations(engine):
    inspector = inspect(engine)
    tables = inspector.get_table_names()
    for table, additions in {
        "experiments": {
            "model": "VARCHAR(255)",
            "agent_version": "VARCHAR(100)",
            "agent_configuration_snapshot": "JSON",
            "provider_metadata_snapshot": "JSON",
            "group_id": "VARCHAR(100)",
            "group_name": "VARCHAR(255)",
        },
        "runs": {
            "raw_output": "JSON",
            "normalized_output": "JSON",
            "execution_duration_ms": "INTEGER",
            "repetition_id": "VARCHAR(40)",
            "repetition_index": "INTEGER",
        },
        "run_evaluations": {"decision_signature": "JSON"},
        "evaluations": {
            "repetition_id": "VARCHAR(40)",
            "repetition_index": "INTEGER",
        },
    }.items():
        if table not in tables: continue
        columns = {c["name"] for c in inspector.get_columns(table)}
        with engine.begin() as conn:
            for name, definition in additions.items():
                if name not in columns: conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {definition}"))
