# AI Agent Evaluation Platform — Phase 1

This directory adds a FastAPI backend beside the preserved `ML4FinancialNews/` source tree. It provides versioned financial-news experiments, provider management, offline evaluation, and the auditable EGAL evidence-grounded abstention agent.

## Inspection report

The starting workspace contained only the upstream ML4FinancialNews project: a standalone FastAPI demo (`/predict` and `/tickers`), saved model artifacts, data-preparation notebooks, and stock/news CSVs. It had no evaluation-platform API, SQLite database, Phase-2 evaluation dataset, migrations, tests, or experiment runner. Its agent depends on an OpenAI-compatible endpoint and optional local model/data artifacts. The original project has not been changed. A future `ml4financialnews` adapter is deliberately registered as unavailable until Phase 4.

## Implemented foundation

- REST API at `/api` and OpenAPI documentation at `/api/docs` and `/api/redoc`.
- Centralized environment configuration, explicit CORS, safe error envelopes, SQLite metadata, and file-backed artifacts.
- Dataset ingestion for JSON arrays and JSONL with streaming file copy, size limits, filename sanitization, SHA-256 fingerprints, structural/schema validation, bounded validation-error samples, pagination, and immutable snapshots.
- Adapter and provider contracts with deterministic `mock-agent` and `mock` provider. The input mapping prevents evaluator-only fields from being passed to the agent.
- Persisted experiments/runs, background-thread mock execution, immediate per-run completion/failure persistence, SSE progress event, JSONL/CSV export, and reproducibility manifest.
- Offline, annotation-driven evaluation with persisted run-level records, auditable metric summaries, and explicit review/not-assessable outcomes.

## Setup

Create a virtual environment, install dependencies, then run the service:

```powershell
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python -m uvicorn app.main:app --reload
```

The API is then available at `http://127.0.0.1:8000/api/health`; documentation is at `http://127.0.0.1:8000/api/docs`.

## Typical mock workflow

1. `POST /api/datasets/upload` multipart form with `file`, optional `display_name`, and optional JSON `declared_schema`.
2. `POST /api/datasets/{id}/snapshots` after successful validation.
3. `POST /api/experiments` with a snapshot ID, `mock-agent`, `mock`, and an `input_mapping` such as `{ "prompt": "text" }`.
4. `POST /api/experiments/{id}/start`, then inspect runs or subscribe to `/events`.

The mock agent only receives the mapping's target fields. For example, a source `ground_truth` field stays outside agent input when it is absent from `input_mapping`.

## Custom agents

Custom registrations are persistent metadata records, not uploaded executable code. The operational adapter types are:

- `mock` / `custom_python`: a registered name backed by the platform's trusted deterministic mock adapter. Use this to validate schemas, mappings, lifecycle operations, and experiments.
- `http` / `external_http`: a platform-owned HTTP adapter that posts `{ "input": ..., "configuration": ... }` to a configured endpoint. It validates JSON responses and optional output schemas.

Register a mock-compatible agent with `POST /api/agents`:

```json
{
  "id": "document-summarizer-test",
  "display_name": "Document summarizer test adapter",
  "agent_type": "custom_python",
  "adapter_type": "mock",
  "version": "1.0",
  "input_schema": {"type": "object", "required": ["document"]},
  "capabilities": ["structured_input", "structured_output"]
}
```

Use `/validate`, `/test`, `/enable`, and `/disable` for lifecycle checks. Registered agents can be supplied to experiment creation exactly like `mock-agent`; add `agent_configuration` only when the declared configuration schema requires it. Experiments retain the agent version and configuration snapshot (while inline secret-like fields are rejected).

HTTP endpoints must be absolute HTTP(S) URLs with no embedded credentials. Redirects are not followed, output is capped at 1 MiB, and loopback/private/link-local/reserved destinations are blocked by default. For a controlled local-development test server only, set `ALLOW_LOCAL_HTTP_AGENTS=true`. Plaintext credential keys are rejected; secret-reference support is a future addition.

## LLM providers and Kaggle-compatible endpoints

The backend API base is `http://127.0.0.1:8000/api`. It is separate from a provider's inference base URL. Create an `openai_compatible` provider with your own Kaggle endpoint only when it implements `GET {base_url}/models` and/or `POST {base_url}/chat/completions`; the supplied base URL is preserved as-is (apart from a trailing slash), so do not add or remove `/v1` unless your endpoint requires it.

Before storing an API key, set `APP_ENCRYPTION_KEY` to a Fernet key. Generate one with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`. Without a valid key, requests containing `api_key` fail safely and no secret is stored. API responses expose only `api_key_configured`.

Create a provider with `POST /api/providers`:

```json
{"name":"Kaggle LLM","provider_type":"openai_compatible","base_url":"YOUR_KAGGLE_BASE_URL","default_model":"YOUR_MODEL_ID","timeout_seconds":30,"is_active":true}
```

`api_key` is optional. Use `GET /api/providers/{id}/models` when discovery is available; otherwise keep the manually entered `default_model`. `POST /api/providers/{id}/test-connection` performs real bounded discovery and a minimal completion and reports every failed check honestly. Use `PATCH` to retain, replace, or explicitly clear credentials (`{"clear_api_key":true}`); `DELETE` rejects providers retained by historical experiments, which can instead be deactivated.

Custom provider URLs reject credential-bearing URLs and internal network targets by default. For a trusted local test server or local Ollama-compatible endpoint only, set `ALLOW_LOCAL_LLM_PROVIDERS=true`. A real Kaggle inference remains unverified until you supply the URL/model and a successful connection test is run.

Provider administration is intended for local trusted use. The default `TRUSTED_HOSTS` only permits localhost; add an explicitly trusted hostname only when deploying behind suitable authentication and network controls.

## Financial News Analysis baseline agent

`financial_news_analysis` is a version-1.0 baseline LLM agent available through the normal agent and experiment APIs. It receives only a scenario's `input` object; dataset `ground_truth` and `metadata` are never added to its prompt. Use the experiment's `provider_id` to select the saved provider. Optional agent configuration supports `model_override` and `generation_settings`; provider credentials remain in provider storage.

The reusable Pydantic contracts are in `app/schemas/financial_news.py`; the machine-readable dataset envelope schema is `app/schemas/financial_news_dataset_v1.json`. Dataset records use `record_schema_version: "1.0"` and must contain `scenario_id`, category (`normal`, `ambiguous`, or `failure`), `input`, and evaluator-only `ground_truth`. A three-scenario synthetic fixture is at `data/fixtures/financial_news_scenarios_v1.jsonl`.

The successful agent output uses schema version `1.0` with sentiment, price impact, BUY/HOLD/SELL recommendation, confidence, nullable numeric forecast, evidence-linked reasoning/factors, missing information, and source IDs. `HOLD` is an ordinary baseline recommendation; it is not EGAL abstention, and this agent does not produce `ABSTAIN`. Confidence is model-reported, not calibrated.

`provided_evidence` is the default and never searches externally. `tavily_live` is optional: set `TAVILY_SEARCH_ENABLED=true` and `TAVILY_API_KEY`, plus the documented depth, max-results, and timeout settings in `.env.example`. Live results are normalized to evidence records but are nondeterministic; freeze them into a JSONL fixture before comparing experimental conditions.

To execute the agent, create a provider, then create an experiment with `agent_id: "financial_news_analysis"` and its `provider_id`. Its runner deliberately extracts only each record's `input` envelope; it does not use `ground_truth` or `metadata`. The agent calls the shared provider layer, stores the provider response in `raw_output`, and stores only the parsed contract in `normalized_output`. Invalid model JSON and provider failures remain explicit run errors; unknown evidence IDs are retained and emitted as validation warnings rather than silently repaired.

## EGAL: Evidence-Grounded Abstention Layer

`financial_news_analysis_egal` is a separate built-in v1.0 agent for comparison with the unchanged baseline. It follows the normal experiment workflow and uses the same saved provider, `model_override`, and `generation_settings`. The runner supplies only the immutable record `input` object to both financial-news agents. EGAL never calls Tavily or another retrieval service: even when `retrieval_mode` is `tavily_live`, it uses only the evidence already frozen in that input.

EGAL performs one original financial-analysis completion, preserves it, validates material evidence-linked claims deterministically against supplied evidence, assesses sufficiency, and makes at most one constrained correction completion. It then revalidates once. If material unsupported claims remain, critical evidence is missing, or the recommendation remains unsupported, EGAL completes with `recommendation: "ABSTAIN"`; it never represents abstention as `HOLD`. Provider errors, malformed output, and other technical failures remain failed runs rather than abstentions.

Its separate `FinancialNewsEgalOutput` contract retains ordinary financial fields and adds `abstention`, `final_claim_validation`, `final_evidence_sufficiency`, and `audit`. The persisted run `raw_output` contains the original and (when used) correction completions; `normalized_output.audit` records original/corrected/final results, validation and sufficiency stages, correction decision, policy/prompt versions, generation provenance, and timings. Inspect it via `GET /api/experiments/{experiment_id}/runs/{run_id}` or the existing run-list endpoint. Offline evaluation accepts both baseline and EGAL output schemas; it treats `ABSTAIN` as a non-action distinct from `HOLD`.

Manual comparison: create two experiments against the same dataset snapshot/provider configuration, one with `financial_news_analysis` and one with `financial_news_analysis_egal`; start both through `POST /api/experiments/{id}/start`, inspect runs, then call the existing evaluation endpoint for each completed experiment. Do not use a live-retrieval dataset to make this comparison unless its retrieved evidence was first frozen into the snapshot.

## Uploading a dataset schema

`POST /api/datasets/upload` is multipart because it includes a dataset file. `declared_schema` is stored and validated as a parsed JSON object. In a browser, multipart cannot transmit a native JavaScript object directly: `FormData.append("declared_schema", object)` becomes the invalid text `[object Object]`. Send either JSON text (`JSON.stringify(schema)`) or an `application/json` file part; the backend parses it once and then validates it as Draft 2020-12 JSON Schema. Omit the field to use the platform's built-in validation for financial-news v1.0 records.

JSONL is preferred: each nonblank line must be an independent JSON object. The API also accepts a `.json` file containing a top-level array. Financial v1.0 records validate the full envelope (`scenario_id`, category, input, ground truth, and metadata), including scenario/category and envelope/input scenario-ID consistency. Validation never puts `ground_truth` or `metadata` into agent input.

## Evaluation engine

Evaluation is offline and never reruns an agent, calls a provider, Tavily, or any LLM. It reads persisted runs and the experiment's immutable dataset snapshot only. Start an idempotent evaluation with `POST /api/experiments/{experiment_id}/evaluations`; inspect evaluations at `GET /api/experiments/{experiment_id}/evaluations`, detailed records at `GET /api/experiments/{experiment_id}/evaluations/{evaluation_id}`, and aggregate results at `GET /api/experiments/{experiment_id}/metrics`.

Results are persisted with schema version `1.0` and metric version `research-metrics-v1`, including claim assessments, validation/reference warnings, exclusions, review requirements, snapshot fingerprint, and a manifest. The four primary metrics are Task Completion (normal), Unsupported Action (ambiguous), Recovery (explicitly recoverable failure scenarios only), and Consistency (the six predefined repeatability IDs, requiring five persisted runs per group). False Success is a supporting check. Undefined or insufficiently annotated outcomes remain `requires_review`, `unscored`, or `not_assessable`; they are never converted into success or zero-percent results.

The included synthetic fixture has minimal annotations and only three scenarios, so it intentionally produces partial/not-assessable evaluation coverage for semantic completion, recovery, and repeatability. It is not the official 18-scenario dataset.

## Tests

Run `.venv\\Scripts\\python.exe -m pytest -q` (or `python -m pytest -q` in an activated environment). `tests/test_egal_agent.py` covers grounded output, one correction maximum, residual abstention, empty evidence, provider failure, prompt isolation, and the audit shape.

## Current boundaries and limitations

- JSONL is streamed for validation and retrieval. JSON arrays require standard JSON decoding and therefore are bounded by the configured upload limit; an incremental JSON parser can be added later if very large JSON arrays are required.
- The worker is an in-process thread abstraction suitable for local development. It is not a durable distributed queue and restart recovery has not been implemented.
- Database initialization uses SQLAlchemy metadata creation as a migration-ready bootstrap. Alembic migration files are not yet included.
- Production authentication/authorization, manual semantic adjudication workflows, EGAL, and ML4FinancialNews baseline execution are intentionally deferred.
