import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";

import { api } from "../api";
import { BrandHeader } from "../components/BrandHeader";
import { ErrorMessage, Loading } from "../components/Status";
import type { Finding } from "../types";

export function FindingPage() {
  const { runId = "", index = "0" } = useParams();
  const findingIndex = Number(index);
  const navigate = useNavigate();
  const [finding, setFinding] = useState<Finding | null>(null);
  const [markdown, setMarkdown] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getFinding(runId, findingIndex)
      .then((loaded) => {
        setFinding(loaded);
        setMarkdown(loaded.cluster.draft_markdown || loaded.cluster.summary);
      })
      .catch((requestError: unknown) =>
        setError(
          requestError instanceof Error
            ? requestError.message
            : "Could not load the finding.",
        ),
      );
  }, [findingIndex, runId]);

  async function approve(event: React.FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError(null);
    try {
      const payload = await api.approveFinding(runId, findingIndex, markdown);
      navigate(`/documents/${payload.document.slug}`);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Could not approve the document.",
      );
    } finally {
      setSaving(false);
    }
  }

  async function reject() {
    setSaving(true);
    try {
      setFinding(await api.rejectFinding(runId, findingIndex));
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Could not reject the finding.",
      );
    } finally {
      setSaving(false);
    }
  }

  if (error && !finding)
    return (
      <>
        <BrandHeader
          suffix="Finding"
          tagline="Repository-backed documentation review"
        />
        <main className="finding-page">
          <ErrorMessage message={error} />
        </main>
      </>
    );
  if (!finding) return <Loading label="Loading finding…" />;

  const { cluster } = finding;
  const sourceCount =
    finding.source_issues.length + finding.source_pull_requests.length;
  return (
    <>
      <BrandHeader
        suffix="Finding"
        tagline={`${finding.repo} · repository-backed documentation review`}
      >
        <nav className="topnav">
          <Link className="published-link" to="/findings">
            Browse findings
          </Link>
          <Link className="published-link" to="/">
            Run agent →
          </Link>
        </nav>
      </BrandHeader>
      <main className="finding-page">
        <article className={`finding-card sev-${cluster.severity}`}>
          <div className="finding-kicker">
            <span className={`sev-pill sev-${cluster.severity}`}>
              {cluster.severity.toUpperCase()}
            </span>
            <span>
              {cluster.finding_type === "shipped_change"
                ? "SHIPPED CHANGE"
                : "OPEN GAP"}
            </span>
            <span>{sourceCount} sources</span>
            <span>confidence {Math.round(cluster.confidence * 100)}%</span>
          </div>
          <h2>{cluster.name}</h2>
          <p className="finding-question">{cluster.recurring_question}</p>
          <p className="finding-summary">{cluster.summary}</p>
          <section className="workflow-strip" aria-label="Finding workflow">
            {[
              "Review repository evidence",
              "Refine the Markdown",
              "Approve document",
              "Create docs PR",
            ].map((label, step) => (
              <div
                className={`workflow-step ${step < 2 || (step === 2 && finding.approved_document) || (step === 3 && finding.documentation_change) ? "active" : ""}`}
                key={label}
              >
                <span>{step + 1}</span>
                <strong>{label}</strong>
              </div>
            ))}
          </section>
          {finding.approved_document ? (
            <section className="approval-callout">
              <div>
                <div className="review-label">Approved document</div>
                <h3>This revision is ready to reuse</h3>
                <p>
                  Open the document to copy it or prepare a documentation pull
                  request.
                </p>
              </div>
              <Link
                className="publish-btn"
                to={`/documents/${finding.approved_document.slug}`}
              >
                Open approved document
              </Link>
            </section>
          ) : null}
          <section className="finding-section">
            <div className="review-label">Repository evidence</div>
            <h3>Review the source material</h3>
            {finding.source_issues.length ? (
              <ul className="source-list">
                {finding.source_issues.map((issue) => (
                  <li key={issue.number}>
                    <a href={issue.url} target="_blank" rel="noreferrer">
                      #{issue.number} {issue.title}
                    </a>
                    <span>
                      {issue.state} · {issue.comments_count} comments
                    </span>
                  </li>
                ))}
              </ul>
            ) : null}
            {finding.source_pull_requests.length ? (
              <ul className="source-list">
                {finding.source_pull_requests.map((pullRequest) => (
                  <li key={pullRequest.number}>
                    <a href={pullRequest.url} target="_blank" rel="noreferrer">
                      Merged PR #{pullRequest.number} {pullRequest.title}
                    </a>
                    <span>merged {pullRequest.merged_at.slice(0, 10)}</span>
                  </li>
                ))}
              </ul>
            ) : null}
            {sourceCount === 0 ? (
              <p className="finding-summary">
                No repository source details are available for this finding.
              </p>
            ) : null}
          </section>
          <section className="review-box finding-section draft-editor-section">
            <div className="review-label">Human review draft</div>
            <h3>{cluster.draft_title || cluster.name}</h3>
            <p>{cluster.draft_summary || cluster.summary}</p>
            <form className="approval-form" onSubmit={approve}>
              <label htmlFor="markdown-editor">
                Edit the Markdown before approving
              </label>
              <textarea
                id="markdown-editor"
                className="markdown-editor"
                value={markdown}
                onChange={(event) => setMarkdown(event.target.value)}
                spellCheck
                required
              />
              <div className="approval-form-actions">
                <span>
                  The approved revision will be saved and opened as a standalone
                  document.
                </span>
                <div className="gap-actions">
                  <button
                    className="reject-btn"
                    type="button"
                    onClick={reject}
                    disabled={saving || cluster.review_status === "rejected"}
                  >
                    {cluster.review_status === "rejected"
                      ? "Rejected"
                      : "Reject"}
                  </button>
                  <button
                    className="publish-btn"
                    type="submit"
                    disabled={saving}
                  >
                    {saving
                      ? "Saving…"
                      : finding.approved_document
                        ? "Update and open"
                        : "Approve and open"}
                  </button>
                </div>
              </div>
              {error ? (
                <div className="pr-alert" role="alert">
                  {error}
                </div>
              ) : null}
            </form>
          </section>
        </article>
      </main>
    </>
  );
}
