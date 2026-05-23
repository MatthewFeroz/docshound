import asyncio
import json
from pathlib import Path

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from app import events
from app.agent import run_agent
from app.payments import require_payment
from app.render import render_events
from app.state import RUNS, AgentState, RunRequest, RunResponse
from app.tools.senso import publish_citeable

WEB_DIR = Path(__file__).parent / "web"
templates = Jinja2Templates(directory=str(WEB_DIR / "templates"))

app = FastAPI(title="Docs Gap Agent", version="0.2.0")
app.mount("/static", StaticFiles(directory=str(WEB_DIR / "static")), name="static")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
async def index(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "index.html",
        {"default_repo": "DataDog/dd-trace-py"},
    )


@app.post("/runs", dependencies=[Depends(require_payment)])
async def create_run_api(request: RunRequest) -> dict[str, str]:
    state = AgentState(repo=request.repo, dry_run=request.dry_run)
    RUNS[state.run_id] = state
    asyncio.create_task(run_agent(request, state=state))
    return {"run_id": state.run_id}


@app.post("/web/runs", response_class=HTMLResponse)
async def create_run_web(
    request: Request,
    repo: str = Form(...),
    docs_url: str | None = Form("https://ddtrace.readthedocs.io/"),
    limit: int = Form(50),
) -> HTMLResponse:
    run_request = RunRequest(
        repo=repo,
        docs_url=docs_url,
        limit=limit,
        dry_run=False,
    )
    state = AgentState(repo=run_request.repo, dry_run=run_request.dry_run)
    RUNS[state.run_id] = state
    asyncio.create_task(run_agent(run_request, state=state))
    return templates.TemplateResponse(
        request,
        "_partials/run_panel.html",
        {"run_id": state.run_id, "repo": state.repo},
    )


@app.get("/runs/{run_id}", response_model=RunResponse)
async def get_run(run_id: str) -> RunResponse:
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return RunResponse(
        run_id=state.run_id,
        status=state.status,
        repo=state.repo,
        dry_run=state.dry_run,
        issues_scraped=len(state.issues),
        clusters_found=len(state.clusters),
        docs_sources=state.docs_sources,
        top_gaps=state.clusters,
        decisions=state.decisions,
        errors=state.errors,
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


@app.post("/runs/{run_id}/gaps/{index}/publish", response_class=HTMLResponse)
async def publish_gap(request: Request, run_id: str, index: int) -> HTMLResponse:
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if index < 0 or index >= len(state.clusters):
        raise HTTPException(status_code=404, detail="Gap not found")

    cluster = state.clusters[index]
    publish_result = await publish_citeable(
        run_id=run_id,
        repo=state.repo,
        cluster=cluster,
        dry_run=state.dry_run,
    )
    url = publish_result["url"] or ""
    cluster.published_url = url
    cluster.review_status = "published"
    cluster.senso_content_id = publish_result.get("content_id")
    cluster.senso_version_id = publish_result.get("version_id")
    events.publish(
        run_id,
        {"type": "gap_published", "index": index, "url": url, "sponsor": "senso"},
    )
    return templates.TemplateResponse(
        request,
        "_partials/published.html",
        {"url": url},
    )


@app.post("/runs/{run_id}/gaps/{index}/reject", response_class=HTMLResponse)
async def reject_gap(request: Request, run_id: str, index: int) -> HTMLResponse:
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if index < 0 or index >= len(state.clusters):
        raise HTTPException(status_code=404, detail="Gap not found")

    state.clusters[index].review_status = "rejected"
    events.publish(
        run_id,
        {"type": "gap_rejected", "index": index},
    )
    return templates.TemplateResponse(
        request,
        "_partials/rejected.html",
        {},
    )


@app.post("/runs/{run_id}/api/gaps/{index}/publish")
async def publish_gap_json(run_id: str, index: int) -> dict[str, str]:
    state = RUNS.get(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Run not found")
    if index < 0 or index >= len(state.clusters):
        raise HTTPException(status_code=404, detail="Gap not found")
    cluster = state.clusters[index]
    publish_result = await publish_citeable(
        run_id=run_id,
        repo=state.repo,
        cluster=cluster,
        dry_run=state.dry_run,
    )
    url = publish_result["url"] or ""
    cluster.published_url = url
    cluster.review_status = "published"
    cluster.senso_content_id = publish_result.get("content_id")
    cluster.senso_version_id = publish_result.get("version_id")
    return {"url": url}


@app.get("/runs/{run_id}/events.json")
async def stream_events_json(run_id: str) -> EventSourceResponse:
    if run_id not in RUNS:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_generator():
        async for event in events.subscribe(run_id):
            yield {"event": event["type"], "data": json.dumps(event)}

    return EventSourceResponse(event_generator())
