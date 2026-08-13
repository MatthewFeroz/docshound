# Separate the frontend and backend

Status: Proposed

## Summary

DocsHound should move from a single server-rendered FastAPI application to two
independently deployable applications:

- a static TypeScript frontend built with React and Vite; and
- a FastAPI JSON/SSE backend containing the existing agent, persistence, and
  GitHub integration code.

This is a moderate refactor, not a rewrite. The agent and repository workflows
already live outside the templates. Most of the work is defining complete JSON
contracts for the review and pull-request flows, rebuilding the small HTMX UI
against those contracts, and making backend state safe for deployment.

An MVP split should take roughly 3–5 engineering days. A production-ready split
with managed persistence, durable background work, deployment configuration,
and cutover validation should take roughly 1–2 engineering weeks.

## Why separate them

Today `app/main.py` owns both browser rendering and backend behavior. It:

- mounts static assets;
- renders full pages and HTML fragments with Jinja2;
- accepts HTMX form submissions;
- exposes JSON endpoints;
- streams both rendered HTML and JSON over server-sent events (SSE); and
- invokes application services and persistence directly.

That arrangement is compact and works well locally, but it couples every UI
deployment to the Python service. It also makes frontend previews, independent
scaling, CDN hosting, and frontend-specific CI harder than necessary.

The split should produce these deployment properties:

- frontend assets can be deployed to static hosting and served through a CDN;
- backend changes can be deployed without rebuilding the frontend when the API
  contract is unchanged;
- secrets such as `OPENAI_API_KEY` and GitHub tokens exist only in the backend;
- each application has an independent health check, build, and rollback; and
- the API can support another client without depending on server-rendered HTML.

Separation alone does not make the backend horizontally scalable. The current
SQLite database, process-local `RUNS` cache, process-local SSE queues, and
in-process background tasks are more important deployment constraints and must
be addressed before running multiple backend replicas.

## Current architecture

```text
Browser
  │
  │ HTML forms, HTMX requests, rendered SSE fragments
  ▼
FastAPI (`app/main.py`)
  ├── Jinja2 templates (`app/web/templates`)
  ├── static assets (`app/web/static`)
  ├── JSON and form routes
  ├── in-process agent tasks
  ├── process-local run cache and event queues
  └── SQLite (`data/docshound.db`)
```

The application already has useful seams:

- agent execution is in `app/agent.py` and `app/langgraph_agent.py`;
- repository and documentation operations are in `app/tools/`;
- approved document and pull-request operations are in dedicated modules; and
- run state is represented by Pydantic models in `app/state.py`.

The primary coupling is in `app/main.py`, where transport concerns, HTML
rendering, response models, and application operations share one router.

## Target architecture

Keep both applications in this repository during the migration so one change
can update an API contract and its consumer atomically.

```text
docshound/
  backend/
    app/
      api/              # versioned JSON and SSE routers
      services/         # application use cases
      repositories/     # persistence interfaces and implementations
      tools/             # GitHub and documentation integrations
    tests/
    requirements.txt
  frontend/
    src/
      api/              # generated types and API client
      components/
      pages/
    package.json
    vite.config.ts
  docs/
```

During the first phase, keep the Python modules under the existing `app/`
directory and separate routers in place. Move the directory to `backend/` only
after the API is complete and the frontend no longer imports or depends on
Jinja templates. This keeps early diffs small and rollback straightforward.

The runtime topology becomes:

```text
Static host / CDN                    Backend host
React + Vite SPA  ── HTTPS/SSE ──▶  FastAPI `/api/v1`
                                          │
                                          ├── worker / agent execution
                                          ├── PostgreSQL
                                          └── durable event transport
```

React is proposed because the interface has several stateful workflows—live
run progress, finding review, Markdown editing, and pull-request preview—but it
does not need a frontend server. Vite can produce static assets deployable on
any CDN-backed host. This decision can be revisited without changing the API
contract.

## API contract required by the frontend

All new application endpoints should live under `/api/v1`. Return JSON errors
in one consistent shape, for example:

```json
{
  "error": {
    "code": "run_not_found",
    "message": "Run not found"
  }
}
```

The minimum contract is:

| Method | Endpoint | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Backend health check |
| `POST` | `/api/v1/runs` | Start a repository analysis |
| `GET` | `/api/v1/runs` | List recent runs with pagination |
| `GET` | `/api/v1/runs/{run_id}` | Get run state and findings |
| `GET` | `/api/v1/runs/{run_id}/events` | Stream typed JSON SSE events |
| `GET` | `/api/v1/runs/{run_id}/findings/{index}` | Get one finding and its evidence |
| `POST` | `/api/v1/runs/{run_id}/findings/{index}/approval` | Save an approved Markdown revision |
| `POST` | `/api/v1/runs/{run_id}/findings/{index}/rejection` | Reject a finding |
| `GET` | `/api/v1/documents/{slug}` | Get an approved document |
| `GET` | `/api/v1/documents/{slug}/download` | Download Markdown |
| `POST` | `/api/v1/documents/{slug}/pull-request-preview` | Detect the target and prepare a patch |
| `POST` | `/api/v1/documents/{slug}/pull-request` | Create the reviewed documentation PR |
| `GET` | `/api/v1/documents/{slug}/patch` | Download the prepared patch |

The existing `POST /runs`, `GET /runs/{run_id}`, and JSON SSE route are a useful
start. Finding approval, rejection, document retrieval, and pull-request routes
currently depend on HTML forms, redirects, or rendered templates and need JSON
equivalents.

### SSE event contract

The backend should stream domain events, never rendered HTML. Each event should
have an event ID and a stable envelope:

```json
{
  "id": "01J...",
  "type": "gap_found",
  "run_id": "...",
  "occurred_at": "2026-08-12T14:00:00Z",
  "data": {}
}
```

Document every event type in the generated OpenAPI schema or a checked-in
schema file. Support SSE reconnection with `Last-Event-ID` before treating the
stream as durable. Until then, the frontend should refetch the run after a
disconnect so it can recover missed state.

## Deployment configuration

### Frontend

The frontend receives only public configuration at build time:

```text
VITE_API_BASE_URL=https://api.example.com
```

No OpenAI or GitHub credential may use a `VITE_` variable or appear in the
frontend bundle.

Configure SPA fallback routing so paths such as `/findings/...` serve
`index.html`. Frontend deployments should run linting, type checking, tests, and
the production build before publishing the static output.

### Backend

The backend retains all secrets and receives runtime configuration:

```text
APP_ENV=production
ALLOWED_ORIGINS=https://app.example.com
DATABASE_URL=postgresql://...
OPENAI_API_KEY=...
OPENAI_MODEL=...
GITHUB_TOKEN=...
GITHUB_WRITE_TOKEN=...
```

Add FastAPI CORS middleware with an explicit allowlist. Do not use wildcard
origins with credentials. Validate configuration at startup and expose a
liveness check separately from any readiness check that depends on storage.

### Persistence and background work

For a single-replica MVP, SQLite can remain on a persistent disk and agent work
can remain in process. Document that this mode does not support horizontal
scaling and may lose an active run when the process restarts.

Before production multi-replica deployment:

1. Replace direct SQLite access with repository interfaces backed by
   PostgreSQL.
2. Move agent execution from `asyncio.create_task` to a durable job queue.
3. Publish run events through a shared transport such as Redis Streams or the
   job system instead of process-local `asyncio.Queue` objects.
4. Persist event IDs or enough run state for SSE reconnect and replay.
5. Remove correctness dependencies on the process-local `RUNS` dictionary.

These changes are deployment hardening rather than frontend work, but omitting
them would leave the separated backend tied to one long-lived process.

## Incremental migration plan

### Phase 1: Establish backend boundaries

- Split `app/main.py` into a versioned API router and a legacy web router.
- Extract route logic into application services that do not import FastAPI,
  Jinja2, `Form`, `Request`, or response classes.
- Introduce Pydantic request and response models for every UI operation.
- Keep existing URLs and templates working.
- Add API contract tests for success, validation, and not-found responses.

Exit criterion: every user action can be completed through `/api/v1` without
rendering an HTML template.

### Phase 2: Build the independent frontend

- Scaffold `frontend/` with React, TypeScript, and Vite.
- Reuse the current visual design and CSS tokens where practical.
- Generate TypeScript types from FastAPI's OpenAPI document in CI.
- Implement the run form, live run timeline, findings list, finding review,
  Markdown approval, document view, patch preview, and PR creation flows.
- Use the browser's native `EventSource` API and refetch state on reconnect.
- Add component tests and one end-to-end happy-path test against the backend.

Exit criterion: the new frontend supports feature parity with the Jinja/HTMX
application against a locally running backend.

### Phase 3: Deploy both applications

- Deploy the backend first with the `/api/v1` contract and explicit CORS
  allowlist.
- Deploy the static frontend with `VITE_API_BASE_URL` pointed at that backend.
- Run smoke tests for run creation, SSE progress, approval, patch preview, and
  PR creation in the deployed environment.
- Keep the legacy UI available during a short validation window.

Exit criterion: production traffic can use the independent frontend without
falling back to a server-rendered route.

### Phase 4: Remove the legacy web layer

- Remove Jinja templates, rendered SSE events, HTMX, and static-file mounting
  from FastAPI.
- Remove HTML form and redirect routes after confirming they have no consumers.
- Move Python source into `backend/` and update local scripts and CI.
- Update the root README with separate local-development and deployment steps.

Exit criterion: the backend serves only JSON, SSE, downloads, health endpoints,
and OpenAPI documentation.

### Phase 5: Make the backend horizontally scalable

- Migrate SQLite to PostgreSQL.
- Introduce durable jobs and shared event delivery.
- Test restart recovery, duplicate job delivery, SSE reconnect, and multiple
  backend replicas.

This phase can occur before Phase 4 if production scale or restart guarantees
are required for the first separated deployment.

## Local development

The intended developer workflow after the split is:

```bash
# Terminal 1
cd backend
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# Terminal 2
cd frontend
npm install
npm run dev
```

The Vite development server should proxy `/api` to `http://127.0.0.1:8000` so
local requests remain same-origin and do not require relaxed development CORS.
Provide one root command later (for example, a Make target) to start both
processes after the directories exist.

## Testing strategy

- Preserve the current Python unit tests throughout the migration.
- Add service tests that run without HTTP or templates.
- Add FastAPI contract tests for every `/api/v1` operation.
- Validate the generated frontend client against the checked-in OpenAPI schema.
- Add frontend tests for loading, empty, failure, and SSE reconnect states.
- Add end-to-end tests for:
  - starting and completing a run;
  - opening, editing, approving, and downloading a finding;
  - rejecting a finding; and
  - previewing a patch and creating a documentation pull request.
- Run a deployed smoke test with credentials stored only in the backend.

## Rollout and rollback

Use a strangler migration: add JSON capabilities while retaining the existing
web routes. Do not remove a legacy route in the same release that introduces
its first frontend replacement.

Rollback should be independently possible:

- point the public application URL back to the legacy FastAPI UI if the new
  frontend fails;
- redeploy the previous static frontend if a frontend-only release fails; or
- roll back the backend while retaining a frontend version compatible with the
  previous API contract.

Avoid breaking changes within `/api/v1`. Introduce `/api/v2` only when a change
cannot be made additively.

## Risks and mitigations

| Risk | Mitigation |
| --- | --- |
| Missed events after disconnect | Refetch run state; later add event IDs and replay |
| API and frontend drift | Generate TypeScript types from OpenAPI and test them in CI |
| Secrets exposed in the bundle | Keep secrets backend-only and scan built assets/config |
| Cross-origin failures | Explicit production allowlist and same-origin local proxy |
| Big-bang regression | Maintain the legacy UI until deployed feature parity passes |
| Active jobs lost on restart | Document MVP limitation; introduce a durable job queue |
| SQLite limits scaling | Use persistent disk for MVP; migrate to PostgreSQL for replicas |
| Duplicate PR creation | Preserve and test the existing idempotent PR workflow |

## Definition of done

The separation is complete when:

- frontend and backend build, test, deploy, and roll back independently;
- the browser communicates only through the documented `/api/v1` contract;
- the backend no longer renders application HTML;
- OpenAI and GitHub secrets exist only in backend runtime configuration;
- every current user workflow has automated API and end-to-end coverage;
- deployed SSE reconnect behavior is verified; and
- the chosen persistence/job architecture matches the documented replica and
  restart guarantees.

## Explicit non-goals

- changing the agent, clustering, drafting, or GitHub research behavior;
- redesigning the user interface during the separation;
- adopting server-side rendering in the new frontend;
- exposing OpenAI or GitHub credentials to the browser; and
- combining the migration with unrelated model or observability changes.
