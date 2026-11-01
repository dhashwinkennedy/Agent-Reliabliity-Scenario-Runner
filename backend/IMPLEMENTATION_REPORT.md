# Implementation report

## EGAL backend implementation

The backend mounts its router at `/api` in `app/main.py`. Experiments reference immutable dataset snapshots; `app/services/experiments.py` extracts only each financial record's `input` before invoking a registered agent and persists raw and normalized results on the existing `Run`. Provider access goes through `app/services/providers.py`, and offline evaluation reads persisted runs and snapshots through `app/services/evaluation.py`.

`financial_news_analysis_egal` is registered alongside (not in place of) `financial_news_analysis`. EGAL uses the same provider configuration and executes: original completion, deterministic supplied-evidence claim validation, sufficiency assessment, at most one correction completion, one revalidation, then either the validated output or explicit `ABSTAIN`. It never calls Tavily/live retrieval and never places dataset ground truth or metadata in provider prompts. The baseline contract remains BUY/HOLD/SELL only.

The separate `FinancialNewsEgalOutput v1.0` includes machine-readable claim/sufficiency/abstention results and an audit record. Existing run fields persist original and correction raw completions plus the final normalized EGAL output, so no new database schema is needed. Provider or schema failures remain failed executions, not abstentions. Existing offline evaluation accepts both contracts and treats ABSTAIN as a non-action.

## Implemented and smoke-verified

- Application import, database bootstrap, health route, and mock agent/provider discovery.
- SQLite metadata models for datasets, snapshots, experiments, and runs.
- Controlled filesystem storage, SHA-256 streaming fingerprints, generic JSON/JSONL structural validation, optional JSON Schema validation, paginated reads, safe deletion retention rule, and snapshots.
- Mock-only experiment execution, input mapping isolation, run persistence, result/export/manifest APIs, and an SSE snapshot event.

Direct verification completed with Python 3.14: application import, `Base.metadata.create_all`, health response, and registry responses.

## Implemented, awaiting full suite verification

`tests/test_api.py` exercises upload-to-run integration and field isolation with FastAPI's test client. The supplied Python 3.14 runtime preinstalls FastAPI 0.139, whose Starlette/AnyIO synchronous `TestClient` portal hangs before request dispatch. This is not represented as a passing suite. `requirements.txt` constrains FastAPI to the stable 0.110–0.129 range; run `python -m pytest -q` in a fresh supported Python 3.12/3.13 environment after installing it.

## Stubbed / deliberately unavailable

- ML4FinancialNews adapter: exposed in agent discovery with `ready: false`; no source was altered and no baseline was run.

## Not implemented

- PostgreSQL migration scripts/Alembic, durable workers/restart recovery, authentication, provider credential persistence, full OpenAI/Ollama providers, and official research execution.

## Custom-agent extension

Implemented persistent `agent_registrations`, trusted mock and HTTP adapter resolution, JSON Schema input/output/configuration checks, registration/update/validation/test/enable/disable/retire APIs, agent version/configuration provenance on experiments, and raw-versus-normalized run outputs. Additive SQLite migration code preserves existing databases. No custom Python files, ZIPs, repository URLs, or dynamic module paths are accepted or executed.

HTTP agents are operational only for explicitly configured endpoints and enforce protocol/credential/redirect/output-size/timeout restrictions plus default private-network blocking. The supplied environment was not used to contact an external service; `tests/test_custom_agent_unit.py` covers trusted mock schema behavior and loopback rejection without network access.

## Known limitations

JSONL parsing is incremental. JSON uses the standard decoder and is subject to the configured upload cap; it is not an unlimited-size JSON-array parser. SSE currently emits a single current progress snapshot per request; a persistent event broker is deferred with the durable worker architecture.
