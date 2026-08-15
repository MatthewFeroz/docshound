from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, Field, HttpUrl, field_validator, model_validator

RunOutcome = Literal[
    "in_progress",
    "recommendations_found",
    "no_activity",
    "no_recommendations",
    "partial_failure",
    "failed",
]


class DocumentationSource(BaseModel):
    kind: Literal["github", "website"] = "github"
    repo: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
    )
    root: str | None = None
    url: str | None = None
    confidence: float = Field(default=0.5, ge=0, le=1)
    discovered_by: str = "user_override"
    page_count: int | None = Field(default=None, ge=0)

    @field_validator("root")
    @classmethod
    def validate_root(_cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip().strip("/")
        if not normalized:
            return None
        if any(part in {".", ".."} for part in normalized.split("/")):
            raise ValueError("Documentation root cannot contain relative path segments")
        return normalized


class RunRequest(BaseModel):
    repo: str = Field(
        pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$",
    )
    docs_url: str | None = None
    documentation_source: DocumentationSource | None = None
    include_documentation_activity: bool = True
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
    source_repo: str | None = None


class PullRequest(BaseModel):
    number: int
    title: str
    body: str | None = None
    url: HttpUrl
    state: str
    merged_at: datetime | None = None
    labels: list[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    source_repo: str | None = None


class DocSource(BaseModel):
    title: str
    url: str
    snippet: str
    source_type: str = "official_docs"
    confidence: float = Field(ge=0, le=1)
    repository_path: str | None = None


class DocumentationCoverage(BaseModel):
    status: Literal[
        "missing", "partial", "documented", "in_progress", "unable_to_verify"
    ] = "unable_to_verify"
    rationale: str
    recommended_action: Literal["create_page", "update_page", "no_change"]
    recommended_path: str | None = None
    relevant_sources: list[DocSource] = Field(default_factory=list)


class GapCluster(BaseModel):
    name: str
    summary: str
    recurring_question: str
    issue_numbers: list[int]
    pr_numbers: list[int] = Field(default_factory=list)
    issue_refs: list[str] = Field(default_factory=list)
    pr_refs: list[str] = Field(default_factory=list)
    finding_type: Literal["open_gap", "shipped_change"] = "open_gap"
    severity: Literal["low", "medium", "high"]
    confidence: float = Field(ge=0, le=1)
    draft_title: str | None = None
    draft_summary: str | None = None
    draft_markdown: str | None = None
    review_status: Literal[
        "pending_review", "approved", "rejected", "published", "no_change_needed"
    ] = "pending_review"
    approved_document_slug: str | None = None
    documentation_coverage: DocumentationCoverage | None = None


class AgentState(BaseModel):
    run_id: str = Field(default_factory=lambda: str(uuid4()))
    repo: str
    dry_run: bool = True
    documentation_source: DocumentationSource | None = None
    include_documentation_activity: bool = True
    started_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    issues: list[Issue] = Field(default_factory=list)
    pull_requests: list[PullRequest] = Field(default_factory=list)
    clusters: list[GapCluster] = Field(default_factory=list)
    docs_sources: list[DocSource] = Field(default_factory=list)
    docs_candidates_inspected: int = 0
    documentation_issues_scraped: int = 0
    documentation_pull_requests_scraped: int = 0
    next_action: str | None = None
    decisions: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    status: Literal["running", "completed", "completed_with_errors", "failed"] = (
        "running"
    )
    outcome: RunOutcome = "in_progress"
    summary: str = "Run is in progress."

    @model_validator(mode="after")
    def restore_terminal_outcome(self) -> "AgentState":
        """Populate the outcome for runs saved before the outcome contract existed."""
        if self.status != "running" and self.outcome == "in_progress":
            from app.run_outcomes import apply_run_outcome

            apply_run_outcome(self)
        return self


class RunResponse(BaseModel):
    run_id: str
    status: str
    outcome: RunOutcome
    summary: str
    repo: str
    dry_run: bool
    documentation_source: DocumentationSource | None = None
    issues_scraped: int
    pull_requests_scraped: int
    clusters_found: int
    docs_sources: list[DocSource] = Field(default_factory=list)
    docs_candidates_inspected: int = 0
    documentation_issues_scraped: int = 0
    documentation_pull_requests_scraped: int = 0
    top_gaps: list[GapCluster]
    decisions: list[dict] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


RUNS: dict[str, AgentState] = {}
