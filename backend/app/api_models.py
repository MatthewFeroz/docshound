from pydantic import BaseModel, ConfigDict, Field, SecretStr

from app.state import DocumentationSource, GapCluster, Issue, PullRequest


class CreateRunRequest(BaseModel):
    repo: str = Field(min_length=1)
    docs_url: str | None = None
    documentation_source: DocumentationSource | None = None
    include_documentation_activity: bool = True
    limit: int = Field(default=50, ge=1, le=100)
    dry_run: bool = False


class CreateRunResponse(BaseModel):
    run_id: str
    status: str
    repo: str
    documentation_source: DocumentationSource | None = None


class ResolveSourcesRequest(BaseModel):
    repo: str = Field(min_length=1)


class ResolveSourcesResponse(BaseModel):
    product_repo: str
    documentation_sources: list[DocumentationSource]
    selected_source: DocumentationSource
    documentation_activity_repos: list[str]


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
    publish_repo: str | None
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
    suggested_target_repo: str | None = None
    write_enabled: bool


class RuntimeConfigResponse(BaseModel):
    write_enabled: bool
    llm_gateway: str | None = None
    llm_primary_model: str | None = None
    llm_fallback_model: str | None = None
    llm_configured: bool
    credential_input_enabled: bool
    github_configured: bool
    github_server_configured: bool
    github_account: str | None = None
    github_verified_repo: str | None = None
    github_document_fetch_limit: int
    github_documents_per_finding: int


class LLMCredentialRequest(BaseModel):
    api_key: SecretStr = Field(min_length=1, max_length=4096)


class GitHubCredentialRequest(BaseModel):
    repo: str = Field(min_length=1)
    api_key: SecretStr | None = Field(default=None, max_length=4096)
