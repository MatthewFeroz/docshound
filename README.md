# DocsHound

<p align="center">
  <img src="frontend/public/logos/docshound-logo.svg" alt="DocsHound" width="180">
</p>

DocsHound turns open issues and merged pull requests into grounded, reviewable
documentation updates.

The project contains two independently deployable applications:

- `frontend/` — React, TypeScript, and Vite static application
- `backend/` — FastAPI JSON/SSE API and agent runtime

The browser never receives model-provider, Merge Gateway, or GitHub
credentials. All secrets stay in the backend runtime.

## Product flow

```text
Repository activity
        ↓
Open gaps + shipped changes
        ↓
Search relevant first-party documentation
        ↓
Assess coverage: missing, partial, or documented
        ↓
Grounded Markdown draft for missing or partial coverage
        ↓
Human review and approval
        ↓
New-page or existing-page patch preview
        ↓
Documentation pull request
```

## Run locally

Requires Python 3.11+, Node.js 20.19+ (or 22.12+), and npm.

Set up the backend:

```bash
cd backend
python3.11 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
cd ..
```

Set up the frontend:

```bash
cd frontend
npm install
cd ..
```

Start both development servers:

```bash
./run.sh
```

Open [http://127.0.0.1:5173](http://127.0.0.1:5173). Vite proxies `/api`
requests to the backend at `http://127.0.0.1:8000`.

You can also run each application independently:

```bash
./backend/run.sh
npm --prefix frontend run dev
```

## Backend configuration

Add credentials to `backend/.env` (or a root `.env` for compatibility with
existing local installations):

```text
GITHUB_TOKEN=          # optional: higher read limits
GITHUB_WRITE_TOKEN=    # optional: create documentation branches and PRs
MERGE_GATEWAY_API_KEY= # recommended: model-based analysis through Gateway
MERGE_GATEWAY_PRIMARY_MODEL=google/gemini-3.7-flash
MERGE_GATEWAY_FALLBACK_MODEL=openai/gpt-5.6-luna
OPENAI_API_KEY=        # optional legacy direct-provider fallback
OPENAI_MODEL=gpt-4o-mini
ALLOWED_ORIGINS=http://localhost:5173
DOCSHOUND_DB_PATH=     # optional: explicit shared SQLite path
```

For pull-request creation, use a fine-grained GitHub token limited to the target
documentation repositories with Contents and Pull requests read/write access.

## Frontend configuration

`VITE_API_BASE_URL` is the only frontend environment variable. Set it to the
public backend origin for independent deployments:

```text
VITE_API_BASE_URL=https://api.example.com
```

Values prefixed with `VITE_` are public and embedded in the browser bundle.
Never place Merge Gateway, model-provider, or GitHub credentials in the
frontend environment.

### OpenTelemetry and OpenInference tracing

DocsHound can export traces to any OTLP/HTTP-compatible collector. Each run is
an OpenInference `AGENT` span, repository operations are `TOOL` spans, and the
LangChain, LangGraph, and OpenAI-compatible Gateway calls beneath them are
instrumented automatically. Model spans include the requested provider/model,
the model returned by Gateway, and whether DocsHound used its fallback route.

Set a collector base URL to enable tracing:

```text
OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4318
OTEL_SERVICE_NAME=docshound
```

Standard options including `OTEL_EXPORTER_OTLP_TRACES_ENDPOINT`,
`OTEL_EXPORTER_OTLP_HEADERS`, `OTEL_RESOURCE_ATTRIBUTES`, and
`OTEL_SDK_DISABLED` are supported. Set `OPENINFERENCE_HIDE_INPUTS=true` and/or
`OPENINFERENCE_HIDE_OUTPUTS=true` when model content must not be captured by
automatic instrumentation. DocsHound's custom spans record repository identity
and result counts, not issue, pull-request, or document bodies.

## Docker

Build and run both applications locally:

```bash
docker compose up --build
```

Open [http://localhost:8080](http://localhost:8080). The backend is available at
`http://localhost:8000`, with persistent SQLite data in a named Docker volume.

Each directory also has its own Dockerfile, so the frontend and backend can be
built, deployed, scaled, and rolled back separately. Configure the backend's
`ALLOWED_ORIGINS` with the deployed frontend origin.

## API

The versioned backend API is under `/api/v1`. Interactive OpenAPI documentation
is available at `http://127.0.0.1:8000/docs`.

Start a run:

```bash
curl -sS -X POST http://127.0.0.1:8000/api/v1/runs \
  -H 'Content-Type: application/json' \
  -d '{"repo":"GoogleCloudPlatform/knowledge-catalog","limit":50}'
```

Then fetch its state or subscribe to JSON server-sent events:

```bash
curl -sS http://127.0.0.1:8000/api/v1/runs/<RUN_ID>
curl -N http://127.0.0.1:8000/api/v1/runs/<RUN_ID>/events
```

The API also exposes findings, approval/rejection, approved documents,
repository patch previews, patch downloads, and pull-request creation.

For compatibility with existing integrations, `POST /runs`,
`GET /runs/{run_id}`, and `GET /runs/{run_id}/events.json` remain available as
aliases for the original DocsHound API contract. New integrations should use
the versioned `/api/v1` routes.

## Persistence

The backend stores local application state in `backend/data/docshound.db`. When
upgrading an existing source checkout, it automatically continues using
`data/docshound.db` if that legacy database exists and the new path does not.
No data is copied or deleted. Set `DOCSHOUND_DB_PATH` when a deployment needs an
explicit shared location.

The database includes completed runs, findings, approved document revisions,
prepared patches, and created pull-request metadata.

SQLite and the in-process event stream are appropriate for a single backend
replica. A multi-replica deployment should use shared persistence and event
delivery before scaling horizontally.

## Tests

Run backend tests:

```bash
cd backend
.venv/bin/python -m unittest discover -s tests -v
```

Run frontend checks:

```bash
cd frontend
npm run format:check
npm run typecheck
npm test
npm run build
```

## Project structure

```text
backend/
  app/                    FastAPI API, agent, persistence, and integrations
  tests/                  API and workflow tests
  Dockerfile
frontend/
  src/                    React application and typed API client
  public/                 DocsHound assets
  Dockerfile
docker-compose.yml        Local production-style deployment
run.sh                    Starts both development servers
```
