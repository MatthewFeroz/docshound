import asyncio
import json
import re
from urllib.parse import urlparse

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from app import events
from app.agent import run_agent
from app.api_models import (
    ApproveFindingRequest,
    CreateRunRequest,
    CreateRunResponse,
    DocumentResponse,
    FindingResponse,
    PreviewDocumentationPullRequestRequest,
    RuntimeConfigResponse,
)
from app.approved_documents import (
    ApprovedDocument,
    document_body_markdown,
    get_approved_document,
    get_approved_document_for_gap,
    save_approved_document,
)
from app.config import get_settings
from app.documentation_prs import (
    DocumentationPullRequestError,
    create_documentation_pull_request,
    get_documentation_change,
    prepare_documentation_change,
    write_enabled,
)
from app.run_store import load_run, load_runs, save_run
from app.state import RUNS, AgentState, RunRequest, RunResponse

app = FastAPI(
    title="DocsHound API",
    version="1.0.0",
    description="JSON and SSE API for the DocsHound frontend.",
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().allowed_origin_list,
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["Content-Type", "Last-Event-ID"],
)

REPO_PART_PATTERN = re.compile(r"^[A-Za-z0-9_.-]+$")

for persisted_run in load_runs():
    RUNS.setdefault(persisted_run.run_id, persisted_run)


def _get_run_state(run_id: str) -> AgentState | None:
    state = RUNS.get(run_id)
    if state is None:
        state = load_run(run_id)
        if state is not None:
            RUNS[run_id] = state
    return state


def _require_run(run_id: str) -> AgentState:
    state = _get_run_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return state


def _normalize_repo(value: str) -> str:
    raw = value.strip()
    if not raw:
        raise ValueError("Enter a repository such as owner/repository.")

    if "://" in raw:
        parsed = urlparse(raw)
        if parsed.hostname not in {"github.com", "www.github.com"}:
            raise ValueError("Enter a GitHub repository URL or owner/repository.")
        path = parsed.path
    elif raw.lower().startswith(("github.com/", "www.github.com/")):
        path = raw.split("/", 1)[1]
    else:
        path = raw

    parts = [part for part in path.strip("/").split("/") if part]
    if len(parts) < 2:
        raise ValueError("Enter a repository such as owner/repository.")

    owner = parts[0]
    repo = parts[1]
    if repo.endswith(".git"):
        repo = repo[:-4]
    if not REPO_PART_PATTERN.fullmatch(owner) or not REPO_PART_PATTERN.fullmatch(repo):
        raise ValueError("The repository owner or name contains unsupported characters.")
    return f"{owner}/{repo}"


def _run_response(state: AgentState) -> RunResponse:
    return RunResponse(
        run_id=state.run_id,
        status=state.status,
        repo=state.repo,
        dry_run=state.dry_run,
        issues_scraped=len(state.issues),
        pull_requests_scraped=len(state.pull_requests),
        clusters_found=len(state.clusters),
        docs_sources=state.docs_sources,
        top_gaps=state.clusters,
        decisions=state.decisions,
        errors=state.errors,
    )


def _finding_response(state: AgentState, index: int) -> FindingResponse:
    if index < 0 or index >= len(state.clusters):
        raise HTTPException(status_code=404, detail="Finding not found")

    cluster = state.clusters[index]
    issue_numbers = set(cluster.issue_numbers)
    pull_request_numbers = set(cluster.pr_numbers)
    approved_document = get_approved_document_for_gap(state.run_id, index)
    documentation_change = None
    if approved_document:
        cluster.approved_document_slug = approved_document.slug
        documentation_change = get_documentation_change(approved_document.slug)

    return FindingResponse(
        run_id=state.run_id,
        repo=state.repo,
        index=index,
        cluster=cluster,
        source_issues=[
            issue for issue in state.issues if issue.number in issue_numbers
        ],
        source_pull_requests=[
            pull_request
            for pull_request in state.pull_requests
            if pull_request.number in pull_request_numbers
        ],
        approved_document=approved_document,
        documentation_change=documentation_change,
    )


def _document_response(document: ApprovedDocument) -> DocumentResponse:
    state = _get_run_state(document.run_id)
    coverage = None
    if state and 0 <= document.gap_index < len(state.clusters):
        coverage = state.clusters[document.gap_index].documentation_coverage
    return DocumentResponse(
        document=document,
        body_markdown=document_body_markdown(document.markdown),
        documentation_change=get_documentation_change(document.slug),
        suggested_file_path=coverage.recommended_path if coverage else None,
        suggested_action=coverage.recommended_action if coverage else None,
        write_enabled=write_enabled(),
    )


def _start_run(request: RunRequest) -> AgentState:
    state = AgentState(repo=request.repo, dry_run=request.dry_run)
    RUNS[state.run_id] = state
    save_run(state)
    asyncio.create_task(run_agent(request, state=state))
    return state


@app.get("/health")
@app.get("/api/v1/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/v1/config", response_model=RuntimeConfigResponse)
async def runtime_config() -> RuntimeConfigResponse:
    return RuntimeConfigResponse(write_enabled=write_enabled())


@app.post("/api/v1/runs", response_model=CreateRunResponse, status_code=202)
async def create_run(request: CreateRunRequest) -> CreateRunResponse:
    try:
        repo = _normalize_repo(request.repo)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    run_request = RunRequest(
        repo=repo,
        docs_url=request.docs_url,
        limit=request.limit,
        dry_run=request.dry_run,
    )
    state = _start_run(run_request)
    return CreateRunResponse(run_id=state.run_id, status=state.status, repo=state.repo)


@app.post("/runs", include_in_schema=False)
async def create_run_legacy(request: RunRequest) -> dict[str, str]:
    """Compatibility route for API clients built against DocsHound 0.x."""
    state = _start_run(request)
    return {"run_id": state.run_id}


@app.get("/api/v1/runs", response_model=list[RunResponse])
async def list_runs() -> list[RunResponse]:
    return [_run_response(state) for state in load_runs()]


@app.get("/runs/{run_id}", response_model=RunResponse, include_in_schema=False)
@app.get("/api/v1/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: str) -> RunResponse:
    return _run_response(_require_run(run_id))


@app.get("/api/v1/findings", response_model=list[FindingResponse])
async def list_findings() -> list[FindingResponse]:
    findings = [
        _finding_response(state, index)
        for state in load_runs()
        for index in range(len(state.clusters))
    ]
    findings.sort(
        key=lambda finding: (
            finding.cluster.approved_document_slug is not None,
            finding.run_id,
        ),
        reverse=True,
    )
    return findings


@app.get(
    "/api/v1/runs/{run_id}/findings/{index}",
    response_model=FindingResponse,
)
async def get_finding(run_id: str, index: int) -> FindingResponse:
    return _finding_response(_require_run(run_id), index)


@app.get("/api/v1/runs/{run_id}/events")
async def stream_events(run_id: str) -> EventSourceResponse:
    state = _require_run(run_id)

    async def event_generator():
        if state.status != "running":
            yield {
                "data": json.dumps(
                    {
                        "type": "run_completed",
                        "run_id": state.run_id,
                        "status": state.status,
                    }
                )
            }
            return

        async for event in events.subscribe(run_id):
            yield {"data": json.dumps(event)}

    return EventSourceResponse(event_generator())


@app.get("/runs/{run_id}/events.json", include_in_schema=False)
async def stream_events_json_legacy(run_id: str) -> EventSourceResponse:
    """Preserve the named JSON event stream exposed by DocsHound 0.x."""
    state = _require_run(run_id)

    async def event_generator():
        if state.status != "running":
            event = {
                "type": "run_completed",
                "run_id": state.run_id,
                "status": state.status,
            }
            yield {"event": event["type"], "data": json.dumps(event)}
            return

        async for event in events.subscribe(run_id):
            yield {"event": event["type"], "data": json.dumps(event)}

    return EventSourceResponse(event_generator())


@app.post(
    "/api/v1/runs/{run_id}/findings/{index}/approval",
    response_model=DocumentResponse,
)
async def approve_finding(
    run_id: str,
    index: int,
    request: ApproveFindingRequest,
) -> DocumentResponse:
    state = _require_run(run_id)
    finding = _finding_response(state, index)
    markdown_source = request.markdown.strip()
    if not markdown_source:
        raise HTTPException(status_code=422, detail="The approved document cannot be empty")

    cluster = finding.cluster
    if cluster.review_status == "no_change_needed":
        raise HTTPException(
            status_code=409,
            detail="Existing documentation already covers this finding.",
        )
    document = save_approved_document(
        run_id=run_id,
        gap_index=index,
        repo=state.repo,
        title=cluster.draft_title or cluster.name,
        summary=cluster.draft_summary or cluster.summary,
        markdown_source=markdown_source,
        source_issues=[
            {"number": issue.number, "title": issue.title, "url": str(issue.url)}
            for issue in finding.source_issues
        ]
        + [
            {
                "number": pull_request.number,
                "title": pull_request.title,
                "url": str(pull_request.url),
                "kind": "pull_request",
            }
            for pull_request in finding.source_pull_requests
        ],
    )
    cluster.draft_markdown = document.markdown
    cluster.review_status = "approved"
    cluster.approved_document_slug = document.slug
    save_run(state)
    events.publish(
        run_id,
        {"type": "gap_approved", "index": index, "title": document.title},
    )
    return _document_response(document)


@app.post(
    "/api/v1/runs/{run_id}/findings/{index}/rejection",
    response_model=FindingResponse,
)
async def reject_finding(run_id: str, index: int) -> FindingResponse:
    state = _require_run(run_id)
    finding = _finding_response(state, index)
    finding.cluster.review_status = "rejected"
    save_run(state)
    events.publish(run_id, {"type": "gap_rejected", "index": index})
    return _finding_response(state, index)


@app.get("/api/v1/documents/{slug}", response_model=DocumentResponse)
async def get_document(slug: str) -> DocumentResponse:
    document = get_approved_document(slug)
    if document is None:
        raise HTTPException(status_code=404, detail="Approved document not found")
    return _document_response(document)


@app.get("/api/v1/documents/{slug}/download")
async def download_document(slug: str) -> Response:
    document = get_approved_document(slug)
    if document is None:
        raise HTTPException(status_code=404, detail="Approved document not found")
    return Response(
        content=document.markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slug}.md"'},
    )


@app.post(
    "/api/v1/documents/{slug}/pull-request-preview",
    response_model=DocumentResponse,
)
async def preview_documentation_pull_request(
    slug: str,
    request: PreviewDocumentationPullRequestRequest,
) -> DocumentResponse:
    document = get_approved_document(slug)
    if document is None:
        raise HTTPException(status_code=404, detail="Approved document not found")
    state = _get_run_state(document.run_id)
    coverage = None
    if state and 0 <= document.gap_index < len(state.clusters):
        coverage = state.clusters[document.gap_index].documentation_coverage
    suggested_path = coverage.recommended_path if coverage else None
    requested_path = request.file_path or suggested_path
    edit_action = None
    if coverage and (not request.file_path or request.file_path == suggested_path):
        edit_action = coverage.recommended_action
    try:
        await prepare_documentation_change(
            document,
            target_repo=request.target_repo,
            requested_path=requested_path,
            edit_action=edit_action,
        )
    except DocumentationPullRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _document_response(document)


@app.post(
    "/api/v1/documents/{slug}/pull-request",
    response_model=DocumentResponse,
)
async def create_documentation_pull_request_route(slug: str) -> DocumentResponse:
    document = get_approved_document(slug)
    if document is None:
        raise HTTPException(status_code=404, detail="Approved document not found")
    change = get_documentation_change(slug)
    if change is None:
        raise HTTPException(status_code=409, detail="Preview the documentation change first")
    try:
        await create_documentation_pull_request(document, change)
    except DocumentationPullRequestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _document_response(document)


@app.get("/api/v1/documents/{slug}/patch")
async def download_documentation_patch(slug: str) -> Response:
    change = get_documentation_change(slug)
    if change is None:
        raise HTTPException(status_code=404, detail="Documentation change not found")
    return Response(
        content=change.patch,
        media_type="text/x-diff; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slug}.patch"'},
    )
