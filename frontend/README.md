# Research Arena — Frontend Platform (v2.0)

A modern, polished React 19 and TypeScript frontend for the **Research Arena AI Agent Evaluation Platform**, engineered against the live FastAPI backend with native support for **Experiment Repetitions**, **Baseline–EGAL Grouping**, and **Automatic Offline Evaluation**.

---

## Key Capabilities

1. **Persistent 6-Section Navigation & Dashboard**
   - Exact sections: **Dashboard**, **Datasets**, **Agents**, **Providers**, **Experiments**, **Analytics**.
   - Live dashboard cards displaying real backend status, dataset counts, registered agents, providers, active/completed experiments, and progress bars.

2. **Datasets & Real Pagination**
   - Upload `.json` and `.jsonl` datasets with multipart form validation.
   - Inspect records with full pagination metadata (`offset`, `limit`, `total`, `has_more`), allowing navigation across >100 records.
   - Trigger re-validation (`POST /api/datasets/{id}/validate`).
   - Create and inspect SHA-256 fingerprinted immutable snapshots.
   - Honest error reporting (e.g. `CANNOT_DELETE_DATASET_WITH_SNAPSHOTS`).

3. **Read-Only Registered Agents Catalog**
   - Displays built-in Baseline (`financial_news_analysis`) and EGAL (`financial_news_analysis_egal`) adapters.
   - Full JSON Schema Draft 2020-12 input and output schema inspector.
   - **Custom agent registration workflows and buttons are strictly omitted** in compliance with frontend specifications.

4. **Model Providers & Security**
   - Register OpenAI, Anthropic, Gemini, or Mock providers.
   - Edit settings, update models, and test connections with real latency diagnostics (`latency_ms`, `reachable`).
   - Plaintext API keys are encrypted at rest with AES-GCM and **never exposed** in client responses, state, or storage.

5. **Central Experiments Workflow & One-Button Rerun**
   - **Create Experiment / Comparison Group:** Configure dataset snapshot, agent, model, provider, temperature, max tokens, and input field mappings with sample record inspection.
   - Supports creating paired Baseline-versus-EGAL comparison groups under a shared human-readable name.
   - **Grouped History:** Experiments are grouped by their actual backend `group_id` / comparison identifier.
   - **One-Button Rerun (Mandatory):** Visible `Rerun Experiment` button creates a new repetition record (`repetition_index` = 2, 3...) using frozen configuration snapshot without recreation or overwriting earlier runs.
   - Debounce and idempotency token guards prevent accidental duplicate submissions on double-clicks or network retries.
   - **Execution Controls:** State-aware `Start`, `Pause`, `Resume`, and `Stop` actions with real-time polling.
   - **Repetition History Table:** Displays every repetition independently with status, run counts, evaluation badges, and direct links to its exact saved data.
   - **Sub-sections:** Overview, Runs (with EGAL audit trail & uncertainty score), Persisted Results, Evaluation Metrics, Provenance Manifest, Input Mapping, and Exports.

6. **Automatic Offline Evaluation for Every Repetition**
   - Zero-click evaluation: When a repetition reaches terminal status (`completed` or `stopped`), the frontend lifecycle automatically requests evaluation for that repetition.
   - Associates the evaluation directly with that repetition's runs without reusing older evaluations.
   - Does not call external LLMs during evaluation.

7. **Analytics — Baseline vs EGAL Comparison**
   - Head-to-head comparison powered by backend `GET /api/experiment-groups/{id}`.
   - Metric direction awareness:
     - Task Completion Rate: Higher is better
     - Unsupported Action Rate: Lower is better (improvements highlighted in emerald)
     - Recovery Rate: Higher is better
     - Consistency Rate: Higher is better
     - False Success: Lower is better
     - Run Coverage: Completeness indicator
   - Authoritative multi-repetition pooled aggregations without harmonic distortion.

---

## Environment Variables

Configure in `.env`:

```bash
# FastAPI Backend base URL
VITE_API_BASE_URL="http://127.0.0.1:8000/api"
```

In development with Vite, requests to `/api` are automatically proxied to `http://127.0.0.1:8000` to avoid CORS issues.

---

## Getting Started

### Development
```bash
# Start Vite development server on port 3000
npm run dev
```

### Run Tests
```bash
# Execute full TypeScript test suite (node:test + tsx)
npm test
```

### Type Checking & Linting
```bash
npm run lint
```

### Production Build
```bash
npm run build
```

---

## Manual Validation Checklist

Follow this checklist to validate the end-to-end integration:

- [ ] **1. Dashboard Verification:** Open `http://localhost:3000`. Confirm all 5 summary cards load actual backend counts and API status indicator displays green "API Connected".
- [ ] **2. Dataset Upload:** Navigate to **Datasets**, click **Upload Dataset**, select `test_dataset.jsonl`. Verify dataset appears with record count.
- [ ] **3. Snapshot Creation:** Click the camera icon on the dataset to create an immutable snapshot. Verify snapshot name and record count.
- [ ] **4. Agent Catalog:** Navigate to **Agents**. Confirm Baseline (`financial_news_analysis`) and EGAL (`financial_news_analysis_egal`) appear as "Ready". Confirm there is **no "Register Custom Agent" button**.
- [ ] **5. Provider Testing:** Navigate to **Providers**. Click **Test Connection** on the mock provider. Verify latency (ms) and success checks appear.
- [ ] **6. Create Paired Group:** Navigate to **Experiments**, click **Create Experiment**. Check "Paired Baseline-versus-EGAL Comparison Group", select the snapshot and mock provider. Submit.
- [ ] **7. Start Execution:** Open the created group. Start Baseline and EGAL. Observe progress bars update in real time.
- [ ] **8. Automatic Evaluation:** Wait for runs to complete. Verify the repetition automatically evaluates and displays accuracy, F1, and abstention rate without clicking an Evaluate button.
- [ ] **9. One-Button Rerun:** Click **Rerun Experiment** on Baseline. Confirm a new `Repetition #2` tab appears, runs are generated fresh, and older Repetition #1 data is preserved intact.
- [ ] **10. Analytics Comparison:** Navigate to **Analytics**. Select the experiment group. Confirm Baseline and EGAL metrics appear side by side with correct delta directions (lower is better for unsupported actions).
