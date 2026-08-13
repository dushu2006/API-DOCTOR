# 🩺 API Doctor — Backend

AI-powered, point-in-time production **diagnosis and repair**. API Doctor reads
the current failure, analyses the stack trace, retrieves only the relevant
source, identifies the root cause, generates a minimal fix, verifies it in an
isolated sandbox, and opens a reviewable GitHub Pull Request. It never modifies
production directly and never auto-merges.

Diagnosis data is deliberately ephemeral. Each user has at most one current run
in process memory. A fresh start replaces it, a backend restart clears it, and
no logs, timeline, context, diff, sandbox result, or PR metadata is stored in the
database.

```
Production error
  → Log/Error detection
  → Fresh in-memory diagnosis
  → Stack-trace analysis
  → Relevant-code retrieval
  → Minimal context
  → AI root-cause analysis
  → AI fix generation
  → Sandbox (reproduce → patch → test → verify)
  → GitHub repair branch → commit → Pull Request
  → Human review
```

---

## Architecture

```
Request → FailureDetector → Ephemeral RunStore → ContextBuilder (StackTraceParser + CodeRetrieval)
         → RootCauseAgent → FixAgent → SandboxRunner (Docker/local)
         → GitHubService (branch → commit → PR) → Dashboard (SSE)
```

```
api-doctor-backend/
├── app/
│   ├── main.py                  # FastAPI app
│   ├── orchestrator.py          # central workflow engine
│   ├── ai/                      # provider abstraction + NVIDIA NIM client
│   ├── agent/                   # root-cause + fix agents (structured JSON)
│   ├── code_retrieval/          # traceback-based + semantic retrieval
│   ├── context_builder/         # minimal, sanitised LLM context
│   ├── demo_api/                # the "patient" (seeded deterministic bugs)
│   ├── detector/                # failure detection (log-source-ready)
│   ├── sandbox/                 # isolated workspace + verification runner
│   ├── github/                  # GitHub client + branch/commit/PR service
│   ├── render/                  # Render client (service/deploy/logs)
│   ├── projects/                # project → repo/branch/Render mapping
│   ├── runs/                    # current-run models, memory store, API router
│   ├── events/                  # live activity hub (SSE)
│   ├── tools/                   # validated, controlled agent tools
│   └── security/                # secret sanitisation
├── tests/                       # unit + integration + e2e
├── requirements.txt
├── .env.example
└── run.py
```

---

## Quick start

### 1. Prerequisites

- Python 3.11+
- Docker Desktop *(optional — set `SANDBOX_MODE=local` to run without Docker)*
- An NVIDIA NIM API key (or any OpenAI-compatible endpoint)

### 2. Setup

```bash
cd api-doctor-backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env        # add your NVIDIA_API_KEY when using NVIDIA NIM
```

### 3. Run

To start the backend, frontend, and browser together from the repository root:

```bash
python ../run.py
```

To start only this backend:

```bash
python run.py               # backend on http://localhost:8000
```

The demo API ("the patient") runs in the same process (in-process ASGI
transport), so the whole demo is self-contained.

### 4. Trigger a diagnosis

```bash
# Deterministic bugs
curl -X POST http://localhost:8000/api/diagnosis/trigger/external_api
curl -X POST http://localhost:8000/api/diagnosis/trigger/config
curl -X POST http://localhost:8000/api/diagnosis/trigger/null_pointer   # <- flagship
curl -X POST http://localhost:8000/api/diagnosis/trigger/schema
```

Each returns a `run_id`. Poll the pipeline:

```bash
curl http://localhost:8000/api/diagnosis/<id>/status    # live progress + activity
curl http://localhost:8000/api/diagnosis/<id>/context   # retrieved context
curl http://localhost:8000/api/diagnosis/<id>/diff      # proposed fix
curl http://localhost:8000/api/diagnosis/<id>/sandbox   # sandbox verification
curl http://localhost:8000/api/diagnosis/<id>/stream    # SSE live progress
curl -X POST http://localhost:8000/api/diagnosis/<id>/cancel
curl -X POST http://localhost:8000/api/diagnosis/<id>/approve
curl -X POST http://localhost:8000/api/diagnosis/<id>/create-pr
```

---

## Seeded bugs (the "patient")

| Scenario        | Endpoint                          | Type                       | Root cause                                   |
| --------------- | --------------------------------- | -------------------------- | -------------------------------------------- |
| `external_api`  | `GET  /api/v1/external/status`    | EXTERNAL_API_FAILURE       | upstream payment provider is down            |
| `config`        | `GET  /api/v1/config`             | CONFIGURATION_ERROR        | reads wrong env var name                     |
| `null_pointer`  | `POST /api/v1/users/user_2/charge`| CODE_BUG (runtime)         | missing null guard on `payment_method`       |
| `schema`        | `GET  /api/v1/orders/order_2`     | CODE_BUG (serialization)   | DB enum value missing from `OrderStatus`     |

All are deterministic and produce **real** Python tracebacks.

---

## AI provider

NVIDIA NIM is the initial provider via an OpenAI-compatible HTTP API. Provider
logic lives behind `app/ai.base.AIClient` so additional providers can be added
without touching the orchestrator or agents. AI selection is independent of
sandbox execution: `AI_PROVIDER=auto` uses NVIDIA when `NVIDIA_API_KEY` is set
and otherwise reports that the deterministic mock is active; use
`AI_PROVIDER=nvidia` or `AI_PROVIDER=mock` to make the choice explicit. Model
routing is purely configuration-driven (never hard-coded):

```
INVESTIGATOR_MODEL=nvidia/nemotron-3-ultra-550b-a55b   # root-cause analysis
CODER_MODEL=z-ai/glm-5.2                               # fix generation
FAST_MODEL=nvidia/nemotron-3-nano-30b-a3b              # health/quick tasks
EMBEDDING_MODEL=nvidia/nv-embedcode-7b-v1              # semantic retrieval
```

Structured outputs are requested as JSON and validated against Pydantic models
with automatic retry-and-repair on validation errors.

---

## Sandbox

The sandbox never touches production:

1. Copies the project source into an isolated temp workspace.
2. **Reproduces** the original failure (confirms the 5xx crash).
3. **Applies** the proposed patch.
4. Runs a **targeted reproduction test**.
5. Runs a **build / syntax check**.
6. Runs a **health check**.
7. **Verifies** the same request no longer crashes.
8. Returns a structured PASS/FAIL result.

Two execution modes:
- `SANDBOX_MODE=docker` — isolated container, network disabled (default).
- `SANDBOX_MODE=local` — subprocess in a temp workspace (no Docker required).

Repair attempts are capped by `MAX_REPAIR_ATTEMPTS` (default 2). On failure the
fix is regenerated with sandbox feedback; after the limit the run stops in
`REPAIR_LIMIT_REACHED`.

---

## GitHub & Render

- **GitHub**: `main → api-doctor/fix/<run-id> → commit → Pull Request`.
  `main` is never modified. Read PR status and GitHub Actions check runs.
- **Render**: isolated behind `RenderClient` (service, deployments, logs). The
  orchestrator never calls the Render API directly.
- **Project mapping** (`app/projects`): stores each project's GitHub repo/branch
  and Render service in the application database. GitHub and Render credentials
  are project-scoped, encrypted at rest, and supplied explicitly to clients.
- **Runtime log viewing**: `GET /api/diagnosis/render-logs?project_id=…` retrieves
  sanitized Render entries for immediate inspection without starting diagnosis.
  `sync-render` reads a new point-in-time window and starts only the first
  detected error as the current run.

---

## Security

- Secrets are **never** sent to the LLM, frontend, browser, logs, or run
  responses.
- `app/security.sanitizer` scrubs API keys, tokens, passwords, authorization
  headers, DB URLs, and env secret values (`DATABASE_URL=<SECRET_PRESENT>`).
- The LLM has **no unrestricted shell access** — only validated, whitelisted
  tools (`read_file`, `search_code`, `apply_patch`, `run_test`, …) via
  `app/tools`.
- Structured, op-scoped logging never includes secret values.

---

## API endpoints

| Method | Path                                  | Purpose                          |
| ------ | ------------------------------------- | -------------------------------- |
| GET    | `/health`                             | liveness + config status         |
| GET    | `/api/diagnosis/current`              | current run or `null`             |
| DELETE | `/api/diagnosis/current`              | fresh start; forget current run   |
| POST   | `/api/diagnosis/start`                | start from pasted logs/trace      |
| GET    | `/api/diagnosis/render-logs`          | view sanitized Render entries     |
| POST   | `/api/diagnosis/sync-render`          | fetch a fresh Render log window   |
| GET    | `/api/diagnosis/{id}`                 | current run detail                |
| POST   | `/api/diagnosis/trigger/{scenario}`   | detect + start a seeded failure  |
| POST   | `/api/diagnosis/{id}/diagnose`        | start/resume diagnosis           |
| POST   | `/api/diagnosis/{id}/restart`      | start fresh from current source  |
| POST   | `/api/diagnosis/{id}/cancel`          | cancel active diagnosis          |
| GET    | `/api/diagnosis/{id}/status`          | live status + activity           |
| GET    | `/api/diagnosis/{id}/context`         | retrieved context                |
| GET    | `/api/diagnosis/{id}/diff`            | proposed fix diff                |
| GET    | `/api/diagnosis/{id}/sandbox`         | sandbox result                   |
| GET    | `/api/diagnosis/{id}/pr`              | PR information                   |
| GET    | `/api/diagnosis/{id}/pr-status`       | PR + checks status               |
| POST   | `/api/diagnosis/{id}/approve`         | human approve / reject           |
| POST   | `/api/diagnosis/{id}/apply-fix`       | idempotently apply verified fix  |
| POST   | `/api/diagnosis/{id}/commit`          | commit applied workspace change  |
| POST   | `/api/diagnosis/{id}/create-pr`       | open the repair PR               |
| GET    | `/api/diagnosis/{id}/stream`          | SSE live agent activity          |
| GET    | `/api/projects` / `/{id}`             | project mapping                  |
| GET    | `/api/tools`                          | list controlled tools            |
| POST   | `/api/benchmark`                      | compare configured models        |

There is intentionally no collection/list endpoint. Detail endpoints work only
for the current in-memory run; an older ID returns `404` after a fresh start.

### Current run lifecycle

`DETECTED → COLLECTING_CONTEXT → INVESTIGATING → ROOT_CAUSE_FOUND → FIX_PLANNED →
SANDBOX_TESTING → VERIFYING → FIX_VERIFIED → PR_CREATED → AWAITING_REVIEW`

Failure states: `INVESTIGATION_FAILED`, `FIX_GENERATION_FAILED`,
`VERIFICATION_FAILED`, `REPAIR_LIMIT_REACHED`.

---

## Testing

```bash
pytest tests/ -v
```

Covers: demo failures, traceback parser, context builder, secret sanitisation,
AI response parsing, patch validation, sandbox, run lifecycle, orchestrator,
GitHub client, Render client, and a full **e2e** flow
(failure → diagnosis → fix → sandbox → verification).

---

## Model benchmark

```bash
python -m app.benchmark                 # CLI
curl -X POST "http://localhost:8000/api/benchmark?task=root_cause"
curl -X POST "http://localhost:8000/api/benchmark?task=patch"
```

Measures time-to-response, total time, output length, success/failure, and
root-cause/patch correctness per configured model — without assuming the largest
model is the fastest or best.
