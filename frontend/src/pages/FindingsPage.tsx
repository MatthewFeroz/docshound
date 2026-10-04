import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";

import { api } from "../api";
import { BrandHeader } from "../components/BrandHeader";
import { ErrorMessage, Loading } from "../components/Status";
import type { Finding } from "../types";

const findingStatuses = {
  pending_review: { label: "Ready to review", className: "preview-pill" },
  approved: { label: "Approved", className: "approved-pill" },
  preview_ready: { label: "Patch ready", className: "approved-pill" },
  branch_ready: { label: "Confirm on GitHub", className: "preview-pill" },
  failed: { label: "Publication failed", className: "rejected-pill" },
  created: { label: "PR created", className: "approved-pill" },
  rejected: { label: "Rejected", className: "rejected-pill" },
  no_change_needed: { label: "No change needed", className: "approved-pill" },
} as const;

type FindingStatus = keyof typeof findingStatuses;

function findingStatus(finding: Finding): FindingStatus {
  const changeStatus = finding.documentation_change?.status;
  if (changeStatus === "created") return changeStatus;
  if (finding.cluster.review_status === "rejected") return "rejected";
  if (
    changeStatus === "branch_ready" ||
    changeStatus === "failed" ||
    changeStatus === "preview_ready"
  )
    return changeStatus;
  if (finding.cluster.review_status === "no_change_needed")
    return "no_change_needed";
  if (finding.cluster.review_status === "published") return "created";
  if (
    finding.approved_document ||
    finding.cluster.approved_document_slug ||
    finding.cluster.review_status === "approved"
  )
    return "approved";
  return "pending_review";
}

export function FindingsPage() {
  const [searchParams, setSearchParams] = useSearchParams();
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const query = searchParams.get("q") || "";
  const requestedStatus = searchParams.get("status") || "";
  const selectedStatus = Object.hasOwn(findingStatuses, requestedStatus)
    ? (requestedStatus as FindingStatus)
    : "";
  const terms = query.trim().toLowerCase().split(/\s+/).filter(Boolean);
  const visibleFindings = (findings || []).filter((finding) => {
    if (selectedStatus && findingStatus(finding) !== selectedStatus)
      return false;
    const text = [
      finding.repo,
      finding.cluster.name,
      finding.cluster.recurring_question,
      finding.cluster.summary,
      finding.cluster.draft_title,
      finding.cluster.draft_summary,
    ]
      .filter(Boolean)
      .join(" ")
      .toLowerCase();
    return terms.every((term) => text.includes(term));
  });
  const hasFilters = Boolean(query.trim() || selectedStatus);

  function updateFilter(name: "q" | "status", value: string) {
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        if (value) next.set(name, value);
        else next.delete(name);
        return next;
      },
      { replace: true },
    );
  }

  function clearFilters() {
    setSearchParams(
      (previous) => {
        const next = new URLSearchParams(previous);
        next.delete("q");
        next.delete("status");
        return next;
      },
      { replace: true },
    );
  }

  useEffect(() => {
    api
      .listFindings()
      .then(setFindings)
      .catch((requestError: unknown) => {
        setError(
          requestError instanceof Error
            ? requestError.message
            : "Could not load findings.",
        );
      });
  }, []);

  return (
    <>
      <BrandHeader
        suffix="Findings"
        tagline="Review open gaps and shipped changes, then approve reusable documentation."
      >
        <nav className="topnav">
          <Link className="published-link" to="/">
            Run agent →
          </Link>
        </nav>
      </BrandHeader>
      <main className="marketplace-page">
        <section className="marketplace-hero">
          <div>
            <div className="review-label">Company view</div>
            <h2>Turn repository activity into useful documentation</h2>
            <p>
              Review unresolved questions and recently shipped changes, refine
              the answer, and approve reusable Markdown.
            </p>
          </div>
          <div className="marketplace-stat">
            <strong>{findings?.length || 0}</strong>
            <span>findings available</span>
          </div>
        </section>
        {error ? <ErrorMessage message={error} /> : null}
        {!error && !findings ? <Loading label="Loading findings…" /> : null}
        {findings?.length ? (
          <section className="findings-controls" aria-label="Filter findings">
            <form
              className="findings-filter-fields"
              role="search"
              onSubmit={(event) => event.preventDefault()}
            >
              <label className="findings-search">
                Search findings
                <input
                  type="search"
                  value={query}
                  onChange={(event) => updateFilter("q", event.target.value)}
                  placeholder="Title, question, or repository"
                />
              </label>
              <label>
                Review status
                <select
                  value={selectedStatus}
                  onChange={(event) =>
                    updateFilter("status", event.target.value)
                  }
                >
                  <option value="">All statuses</option>
                  {Object.entries(findingStatuses).map(([value, status]) => (
                    <option value={value} key={value}>
                      {status.label}
                    </option>
                  ))}
                </select>
              </label>
              {hasFilters ? (
                <button
                  className="reject-btn"
                  type="button"
                  onClick={clearFilters}
                >
                  Clear filters
                </button>
              ) : null}
            </form>
            <p className="findings-result-count" role="status">
              Showing {visibleFindings.length} of {findings.length} findings
            </p>
          </section>
        ) : null}
        {visibleFindings.length ? (
          <section className="marketplace-grid">
            {visibleFindings.map((finding) => {
              const { cluster } = finding;
              const status = findingStatuses[findingStatus(finding)];
              return (
                <article
                  className={`marketplace-card sev-${cluster.severity}`}
                  key={`${finding.run_id}-${finding.index}`}
                >
                  <div className="finding-kicker">
                    <span className={`sev-pill sev-${cluster.severity}`}>
                      {cluster.severity.toUpperCase()}
                    </span>
                    <span>{finding.repo}</span>
                    <span>
                      {cluster.finding_type === "shipped_change"
                        ? "Shipped change"
                        : "Open gap"}
                    </span>
                    <span>
                      {(cluster.issue_refs.length ||
                        cluster.issue_numbers.length) +
                        (cluster.pr_refs.length ||
                          cluster.pr_numbers.length)}{" "}
                      sources
                    </span>
                  </div>
                  <h3>{cluster.name}</h3>
                  <p>{cluster.recurring_question}</p>
                  <div className="marketplace-card-foot">
                    <span className={status.className}>{status.label}</span>
                    <Link
                      className="publish-btn"
                      to={`/runs/${finding.run_id}/findings/${finding.index}`}
                    >
                      View finding
                    </Link>
                  </div>
                </article>
              );
            })}
          </section>
        ) : null}
        {findings?.length && visibleFindings.length === 0 ? (
          <section className="placeholder">
            <div className="placeholder-card">
              <h2>No findings match these filters.</h2>
              <p className="placeholder-hint">
                Try another search or review status, or clear the filters to
                browse all findings.
              </p>
              <button
                className="publish-btn"
                type="button"
                onClick={clearFilters}
              >
                Show all findings
              </button>
            </div>
          </section>
        ) : null}
        {findings?.length === 0 ? (
          <section className="placeholder">
            <div className="placeholder-card">
              <h2>No findings yet.</h2>
              <p className="placeholder-hint">
                Run the agent against a repository to discover documentation
                gaps.
              </p>
              <Link className="publish-btn" to="/">
                Run agent
              </Link>
            </div>
          </section>
        ) : null}
      </main>
    </>
  );
}
