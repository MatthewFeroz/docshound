from pydantic import BaseModel, ConfigDict, Field

from app.state import GapCluster, Issue, PullRequest


class CreateRunRequest(BaseModel):
    repo: str = Field(min_length=1)
    docs_url: str | None = None
    limit: int = Field(default=50, ge=1, le=100)
    dry_run: bool = False


class CreateRunResponse(BaseModel):
    run_id: str
    status: str
    repo: str


class ApprovedDocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    slug: str
    run_id: str
    gap_index: int
    repo: str
    title: str
    summary: str
    markdown: str
    source_issues: list[dict[str, str | int]]
    approved_at: str
    updated_at: str


class DocumentationChangeResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    document_slug: str
    target_repo: str
    base_branch: str
    branch_name: str
    file_path: str
    file_format: str
    detected_by: str
    edit_action: str
    content: str
    patch: str
    existing_sha: str | None
    status: str
    pr_number: int | None
    pr_url: str | None
    error: str | None
    created_at: str
    updated_at: str


class FindingResponse(BaseModel):
    run_id: str
    repo: str
    index: int
    cluster: GapCluster
    source_issues: list[Issue]
    source_pull_requests: list[PullRequest]
    approved_document: ApprovedDocumentResponse | None = None
    documentation_change: DocumentationChangeResponse | None = None


class ApproveFindingRequest(BaseModel):
    markdown: str = Field(min_length=1)


class PreviewDocumentationPullRequestRequest(BaseModel):
    target_repo: str = Field(pattern=r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
    file_path: str | None = None


class DocumentResponse(BaseModel):
    document: ApprovedDocumentResponse
    body_markdown: str
    documentation_change: DocumentationChangeResponse | None = None
    suggested_file_path: str | None = None
    suggested_action: str | None = None
    write_enabled: bool


class RuntimeConfigResponse(BaseModel):
    write_enabled: bool
    llm_gateway: str | None = None
    llm_primary_model: str | None = None
    llm_fallback_model: str | None = None
