import asyncio
import json
import re
from pathlib import Path
from urllib.parse import urlparse

from fastapi import FastAPI, Form, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from app import events
from app.approved_documents import (
    document_body_markdown,
    get_approved_document,
    get_approved_document_for_gap,
    render_markdown,
    save_approved_document,
)
from app.agent import run_agent
from app.documentation_prs import (
    DocumentationPullRequestError,
    create_documentation_pull_request,
    get_documentation_change,
    prepare_documentation_change,
    write_enabled,
)
from app.render import render_events
from app.run_store import load_run, load_runs, save_run
from app.state import RUNS, AgentState, RunRequest, RunResponse

WEB_DIR = Path(__file__).parent / "web"
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))
templates.env.globals["docshound_icon"] = "/static/logos/docshound.png"
templates.env.globals["docshound_logo"] = "/static/logos/docshound.png"

app = FastAPI(title="DocsHound", version="0.2.0")
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")

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


def _gap_context(state: AgentState, index: int) -> dict:
    if index < 0 or index >= len(state.clusters):
        raise HTTPException(status_code=404, detail="Gap not found")
    cluster = state.clusters[index]
    source_issues = [
        issue for issue in state.issues if issue.number in set(cluster.issue_numbers)
    ]
    source_pull_requests = [
        pull_request
        for pull_request in state.pull_requests
        if pull_request.number in set(cluster.pr_numbers)
    ]
    approved_document = get_approved_document_for_gap(state.run_id, index)
    documentation_change = None
    if approved_document:
        cluster.approved_document_slug = approved_document.slug
        documentation_change = get_documentation_change(approved_document.slug)
    return {
        "run_id": state.run_id,
        "repo": state.repo,
        "index": index,
        "cluster": cluster,
        "source_issues": source_issues,
        "source_pull_requests": source_pull_requests,
        "approved_document": approved_document,
        "documentation_change": documentation_change,
    }


def _all_finding_contexts() -> list[dict]:
    findings: list[dict] = []
    for state in RUNS.values():
        for index, _cluster in enumerate(state.clusters):
            findings.append(_gap_context(state, index))
    return findings


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(request, "index.html")


@app.get("/findings", response_class=HTMLResponse)
async def findings_index(request: Request) -> HTMLResponse:
    findings = _all_finding_contexts()
    findings.sort(
        key=lambda item: (
            item["cluster"].approved_document_slug is not None,
            item["run_id"],
        ),
        reverse=True,
    )
    return templates.TemplateResponse(
        request,
        "findings.html",
        {"findings": findings, "finding_count": len(findings)},
    )


@app.post("/runs")
async def create_run_api(request: RunRequest) -> dict[str, str]:
    state = AgentState(repo=request.repo, dry_run=request.dry_run)
    RUNS[state.run_id] = state
    save_run(state)
    asyncio.create_task(run_agent(request, state=state))
    return {"run_id": state.run_id}


@app.post("/web/runs", response_class=HTMLResponse)
async def create_run_web(
    request: Request,
    repo: str = Form(...),
    docs_url: str | None = Form(None),
    limit: int = Form(50),
) -> HTMLResponse:
    try:
        normalized_repo = _normalize_repo(repo)
    except ValueError as exc:
        return templates.TemplateResponse(
            request,
            "_partials/run_error.html",
            {"message": str(exc)},
        )

    run_request = RunRequest(
        repo=normalized_repo,
        docs_url=docs_url,
        limit=limit,
        dry_run=False,
    )
    state = AgentState(repo=run_request.repo, dry_run=run_request.dry_run)
    RUNS[state.run_id] = state
    save_run(state)
    asyncio.create_task(run_agent(run_request, state=state))
    return templates.TemplateResponse(
        request,
        "_partials/run_panel.html",
        {"run_id": state.run_id, "repo": state.repo},
    )


@app.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: str) -> RunResponse:
    state = _get_run_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
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


@app.get("/runs/{run_id}/gaps/{index}", response_class=HTMLResponse)
async def finding_page(request: Request, run_id: str, index: int) -> HTMLResponse:
    state = _get_run_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return templates.TemplateResponse(
        request,
        "finding.html",
        _gap_context(state, index),
    )


@app.get("/runs/{run_id}/events")
async def stream_events(run_id: str) -> EventSourceResponse:
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        async for event in events.subscribe(run_id):
            for sse_event in render_events(event, templates, run_id):
                yield sse_event

    return EventSourceResponse(event_generator())


@app.post("/runs/{run_id}/gaps/{index}/approve")
async def approve_gap(
    run_id: str,
    index: int,
    markdown_source: str = Form(..., alias="markdown"),
) -> RedirectResponse:
    state = _get_run_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if index < 0 or index >= len(state.clusters):
        raise HTTPException(status_code=404, detail="Gap not found")
    if not markdown_source.strip():
        raise HTTPException(status_code=422, detail="The approved document cannot be empty")

    cluster = state.clusters[index]
    source_issues = [
        issue for issue in state.issues if issue.number in set(cluster.issue_numbers)
    ]
    source_pull_requests = [
        pull_request
        for pull_request in state.pull_requests
        if pull_request.number in set(cluster.pr_numbers)
    ]
    document = save_approved_document(
        run_id=run_id,
        gap_index=index,
        repo=state.repo,
        title=cluster.draft_title or cluster.name,
        summary=cluster.draft_summary or cluster.summary,
        markdown_source=markdown_source.strip(),
        source_issues=[
            {"number": issue.number, "title": issue.title, "url": str(issue.url)}
            for issue in source_issues
        ]
        + [
            {
                "number": pull_request.number,
                "title": pull_request.title,
                "url": str(pull_request.url),
                "kind": "pull_request",
            }
            for pull_request in source_pull_requests
        ],
    )
    cluster.draft_markdown = document.markdown
    cluster.review_status = "approved"
    cluster.approved_document_slug = document.slug
    save_run(state)
    events.publish(
        run_id,
        {
            "type": "gap_approved",
            "index": index,
            "title": cluster.draft_title or cluster.name,
        },
    )
    return RedirectResponse(
        url=f"/docs/{document.slug}",
        status_code=303,
    )


@app.get("/docs/{slug}/download")
async def download_approved_document(slug: str) -> Response:
    document = get_approved_document(slug)
    if document is None:
        raise HTTPException(status_code=404, detail="Approved document not found")
    filename = f"{slug}.md"
    return Response(
        content=document.markdown,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.get("/docs/{slug}", response_class=HTMLResponse)
async def approved_document_page(request: Request, slug: str) -> HTMLResponse:
    document = get_approved_document(slug)
    if document is None:
        raise HTTPException(status_code=404, detail="Approved document not found")
    return templates.TemplateResponse(
        request,
        "document.html",
        {
            "document": document,
            "rendered_markdown": render_markdown(
                document_body_markdown(document.markdown)
            ),
            "documentation_change": get_documentation_change(slug),
        },
    )


@app.post("/docs/{slug}/pull-request/preview", response_class=HTMLResponse)
async def preview_documentation_pull_request(
    request: Request,
    slug: str,
    target_repo: str = Form(...),
    file_path: str | None = Form(None),
) -> HTMLResponse:
    document = get_approved_document(slug)
    if document is None:
        raise HTTPException(status_code=404, detail="Approved document not found")
    try:
        change = await prepare_documentation_change(
            document,
            target_repo=target_repo,
            requested_path=file_path,
        )
        error = None
    except DocumentationPullRequestError as exc:
        change = get_documentation_change(slug)
        error = str(exc)
    return templates.TemplateResponse(
        request,
        "documentation_pr.html",
        {
            "document": document,
            "change": change,
            "error": error,
            "write_enabled": write_enabled(),
        },
    )


@app.get("/docs/{slug}/pull-request", response_class=HTMLResponse)
async def documentation_pull_request_page(
    request: Request, slug: str
) -> HTMLResponse:
    document = get_approved_document(slug)
    if document is None:
        raise HTTPException(status_code=404, detail="Approved document not found")
    change = get_documentation_change(slug)
    if change is None:
        return RedirectResponse(url=f"/docs/{slug}", status_code=303)
    return templates.TemplateResponse(
        request,
        "documentation_pr.html",
        {
            "document": document,
            "change": change,
            "error": change.error,
            "write_enabled": write_enabled(),
        },
    )


@app.post("/docs/{slug}/pull-request/create", response_class=HTMLResponse)
async def create_documentation_pull_request_route(
    request: Request, slug: str
) -> HTMLResponse:
    document = get_approved_document(slug)
    if document is None:
        raise HTTPException(status_code=404, detail="Approved document not found")
    change = get_documentation_change(slug)
    if change is None:
        raise HTTPException(status_code=409, detail="Preview the documentation change first")
    try:
        change = await create_documentation_pull_request(document, change)
        error = None
    except DocumentationPullRequestError as exc:
        change = get_documentation_change(slug) or change
        error = str(exc)
    return templates.TemplateResponse(
        request,
        "documentation_pr.html",
        {
            "document": document,
            "change": change,
            "error": error,
            "write_enabled": write_enabled(),
        },
    )


@app.get("/docs/{slug}/pull-request/patch")
async def download_documentation_patch(slug: str) -> Response:
    change = get_documentation_change(slug)
    if change is None:
        raise HTTPException(status_code=404, detail="Documentation change not found")
    return Response(
        content=change.patch,
        media_type="text/x-diff; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{slug}.patch"'},
    )


@app.post("/runs/{run_id}/gaps/{index}/reject", response_class=HTMLResponse)
async def reject_gap(request: Request, run_id: str, index: int) -> HTMLResponse:
    state = _get_run_state(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if index < 0 or index >= len(state.clusters):
        raise HTTPException(status_code=404, detail="Gap not found")

    state.clusters[index].review_status = "rejected"
    save_run(state)
    events.publish(
        run_id,
        {"type": "gap_rejected", "index": index},
    )
    return templates.TemplateResponse(
        request,
        "_partials/rejected.html",
        {},
    )


@app.get("/runs/{run_id}/events.json")
async def stream_events_json(run_id: str) -> EventSourceResponse:
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        async for event in events.subscribe(run_id):
            yield {"event": event["type"], "data": json.dumps(event)}

    return EventSourceResponse(event_generator())
