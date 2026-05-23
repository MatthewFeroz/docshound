from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl


class RunRequest(BaseModel):
    repo: str = Field(
        default="DataDog/dd-trace-py",
        pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
    )
    docs_url: str | None = "https://ddtrace.readthedocs.io/"
    limit: int = Field(default=50, ge=1, le=100)
    dry_run: bool = True


class Issue(BaseModel):
    number: int
    title: str
    body: str | None = None
    url: HttpUrl
    state: str
    labels: list[str] = Field(default_factory=list)
    comments_count: int = 0
    created_at: datetime
    updated_at: datetime


class GapCluster(BaseModel):
    name: str
    summary: str
    recurring_question: str
    issue_numbers: list[int]
    severity: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0, le=1)
    draft_title: str | None = None
    draft_summary: str | None = None
    draft_markdown: str | None = None
    review_status: Literal["pending_review", "approved", "rejected", "published"] = (
        "pending_review"
    )
    senso_content_id: str | None = None
    senso_version_id: str | None = None
    published_url: str | None = None


class DocSource(BaseModel):
    title: str
    url: str
    snippet: str
    source_type: str = "official_docs"
    confidence: float = Field(ge=0, le=1)


class AgentState(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    repo: str
    dry_run: bool = True
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    issues: list[Issue] = Field(default_factory=list)
    clusters: list[GapCluster] = Field(default_factory=list)
    docs_sources: list[DocSource] = Field(default_factory=list)
    next_action: str | None = None
    decisions: list[dict] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    status: Literal["running", "completed", "completed_with_errors", "failed"] = "running"


class RunResponse(BaseModel):
    run_id: str
    status: str
    repo: str
    dry_run: bool
    issues_scraped: int
    clusters_found: int
    docs_sources: list[DocSource] = Field(default_factory=list)
    top_gaps: list[GapCluster]
    decisions: list[dict] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


RUNS: dict[str, AgentState] = {}
