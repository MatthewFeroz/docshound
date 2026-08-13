export type Severity = "low" | "medium" | "high";
export type ReviewStatus =
  "pending_review" | "approved" | "rejected" | "published" | "no_change_needed";

export interface DocSource {
  title: string;
  url: string;
  snippet: string;
  source_type: string;
  confidence: number;
  repository_path: string | null;
}

export interface DocumentationCoverage {
  status: "missing" | "partial" | "documented" | "unable_to_verify";
  rationale: string;
  recommended_action: "create_page" | "update_page" | "no_change";
  recommended_path: string | null;
  relevant_sources: DocSource[];
}

export interface Issue {
  number: number;
  title: string;
  body: string | null;
  url: string;
  state: string;
  labels: string[];
  comments_count: number;
  created_at: string;
  updated_at: string;
}

export interface PullRequest {
  number: number;
  title: string;
  body: string | null;
  url: string;
  state: string;
  merged_at: string;
  labels: string[];
  created_at: string;
  updated_at: string;
}

export interface GapCluster {
  name: string;
  summary: string;
  recurring_question: string;
  issue_numbers: number[];
  pr_numbers: number[];
  finding_type: "open_gap" | "shipped_change";
  severity: Severity;
  confidence: number;
  draft_title: string | null;
  draft_summary: string | null;
  draft_markdown: string | null;
  review_status: ReviewStatus;
  approved_document_slug: string | null;
  documentation_coverage: DocumentationCoverage | null;
}

export interface ApprovedSource {
  number: number;
  title: string;
  url: string;
  kind?: "issue" | "pull_request";
}

export interface ApprovedDocument {
  slug: string;
  run_id: string;
  gap_index: number;
  repo: string;
  title: string;
  summary: string;
  markdown: string;
  source_issues: ApprovedSource[];
  approved_at: string;
  updated_at: string;
}

export interface DocumentationChange {
  document_slug: string;
  target_repo: string;
  base_branch: string;
  branch_name: string;
  file_path: string;
  file_format: string;
  detected_by: string;
  edit_action: "create_page" | "update_page";
  content: string;
  patch: string;
  existing_sha: string | null;
  status: string;
  pr_number: number | null;
  pr_url: string | null;
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface Finding {
  run_id: string;
  repo: string;
  index: number;
  cluster: GapCluster;
  source_issues: Issue[];
  source_pull_requests: PullRequest[];
  approved_document: ApprovedDocument | null;
  documentation_change: DocumentationChange | null;
}

export interface Run {
  run_id: string;
  status: "running" | "completed" | "completed_with_errors" | "failed";
  repo: string;
  dry_run: boolean;
  issues_scraped: number;
  pull_requests_scraped: number;
  clusters_found: number;
  docs_sources: DocSource[];
  top_gaps: GapCluster[];
  decisions: Array<Record<string, unknown>>;
  errors: string[];
}

export interface CreateRunResponse {
  run_id: string;
  status: string;
  repo: string;
}

export interface RuntimeConfig {
  write_enabled: boolean;
  llm_gateway: string | null;
  llm_primary_model: string | null;
  llm_fallback_model: string | null;
}

export interface DocumentPayload {
  document: ApprovedDocument;
  body_markdown: string;
  documentation_change: DocumentationChange | null;
  suggested_file_path: string | null;
  suggested_action: "create_page" | "update_page" | "no_change" | null;
  write_enabled: boolean;
}

export interface RunEvent {
  type: string;
  run_id?: string;
  status?: string;
  name?: string;
  action?: string;
  reason?: string;
  count?: number;
  duration_ms?: number;
  error?: string;
  title?: string;
  index?: number;
  cluster?: GapCluster;
}
