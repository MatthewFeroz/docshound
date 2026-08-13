import { useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api } from "../api";
import { BrandHeader } from "../components/BrandHeader";
import { ErrorMessage, Loading } from "../components/Status";
import type { Finding } from "../types";

export function FindingsPage() {
  const [findings, setFindings] = useState<Finding[] | null>(null);
  const [error, setError] = useState<string | null>(null);

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
          <section className="marketplace-grid">
            {findings.map((finding) => {
              const { cluster } = finding;
              const status =
                finding.documentation_change?.status === "created"
                  ? "PR created"
                  : finding.documentation_change
                    ? "Patch ready"
                    : cluster.approved_document_slug
                      ? "Approved"
                      : cluster.review_status === "rejected"
                        ? "Rejected"
                        : "Ready to review";
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
                      {cluster.issue_numbers.length + cluster.pr_numbers.length}{" "}
                      sources
                    </span>
                  </div>
                  <h3>{cluster.name}</h3>
                  <p>{cluster.recurring_question}</p>
                  <div className="marketplace-card-foot">
                    <span
                      className={
                        status === "Ready to review"
                          ? "preview-pill"
                          : status === "Rejected"
                            ? "rejected-pill"
                            : "approved-pill"
                      }
                    >
                      {status}
                    </span>
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
