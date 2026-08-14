import { Link } from "react-router-dom";

import type { GapCluster } from "../types";

interface GapCardProps {
  cluster: GapCluster;
  index: number;
  runId: string;
  onReject?: () => void;
  rejecting?: boolean;
}

export function GapCard({
  cluster,
  index,
  runId,
  onReject,
  rejecting,
}: GapCardProps) {
  const sourceCount =
    (cluster.issue_refs.length || cluster.issue_numbers.length) +
    (cluster.pr_refs.length || cluster.pr_numbers.length);
  return (
    <article className={`gap-card sev-${cluster.severity}`}>
      <header className="gap-head">
        <span className={`sev-pill sev-${cluster.severity}`}>
          {cluster.severity.toUpperCase()}
        </span>
        <h3>{cluster.name}</h3>
      </header>
      <p className="gap-question">{cluster.recurring_question}</p>
      <p className="gap-summary">{cluster.summary}</p>
      {cluster.review_status === "no_change_needed" ? (
        <section className="review-box">
          <div className="review-label">Documentation coverage</div>
          <h4>Already documented</h4>
          <p>{cluster.documentation_coverage?.rationale}</p>
        </section>
      ) : (
        <section className="review-box">
          <div className="review-label">Human review draft</div>
          <h4>{cluster.draft_title || cluster.name}</h4>
          <p>{cluster.draft_summary || cluster.summary}</p>
          <details>
            <summary>Preview generated Markdown</summary>
            <pre>{cluster.draft_markdown || cluster.summary}</pre>
          </details>
        </section>
      )}
      <footer className="gap-foot">
        <div className="gap-meta">
          <span>
            {cluster.finding_type === "shipped_change"
              ? "shipped change"
              : "open gap"}
          </span>
          <span className="dot-sep">·</span>
          <span>{sourceCount} sources</span>
          <span className="dot-sep">·</span>
          <span>confidence {Math.round(cluster.confidence * 100)}%</span>
          <span className="dot-sep">·</span>
          <span>{cluster.review_status.replaceAll("_", " ")}</span>
        </div>
        <div className="gap-actions">
          <Link className="publish-btn" to={`/runs/${runId}/findings/${index}`}>
            View finding
          </Link>
          {onReject && cluster.review_status !== "rejected" ? (
            <button
              className="reject-btn"
              onClick={onReject}
              disabled={rejecting}
            >
              {rejecting ? "Rejecting…" : "Reject"}
            </button>
          ) : null}
          {cluster.review_status === "rejected" ? (
            <span className="rejected-pill">Rejected by reviewer</span>
          ) : null}
        </div>
      </footer>
    </article>
  );
}
