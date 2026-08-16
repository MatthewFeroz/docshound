import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";

import { api, assetUrl } from "../api";
import { ErrorMessage, Loading } from "../components/Status";
import type { DocumentPayload } from "../types";

export function PullRequestPage() {
  const { slug = "" } = useParams();
  const [payload, setPayload] = useState<DocumentPayload | null>(null);
  const [targetRepo, setTargetRepo] = useState("");
  const [filePath, setFilePath] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getDocument(slug)
      .then((loaded) => {
        setPayload(loaded);
        setTargetRepo(
          loaded.documentation_change?.target_repo || loaded.document.repo,
        );
        setFilePath(loaded.documentation_change?.file_path || "");
      })
      .catch((requestError: unknown) =>
        setError(
          requestError instanceof Error
            ? requestError.message
            : "Could not load the change.",
        ),
      );
  }, [slug]);

  async function refreshPreview(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      const loaded = await api.previewPullRequest(slug, targetRepo, filePath);
      setPayload(loaded);
      setFilePath(loaded.documentation_change?.file_path || filePath);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Could not refresh the preview.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  async function createPullRequest() {
    setSubmitting(true);
    setError(null);
    try {
      setPayload(await api.createPullRequest(slug));
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Could not create the pull request.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (error && !payload)
    return (
      <main className="document-shell pr-page">
        <ErrorMessage message={error} />
      </main>
    );
  if (!payload) return <Loading label="Loading repository change…" />;
  const change = payload.documentation_change;
  const displayError =
    error || (change?.status === "failed" ? change.error : null);

  return (
    <div className="document-shell">
      <header className="document-toolbar">
        <Link className="document-brand" to="/">
          <img src="/logos/docshound.png" alt="" />
          <span>DocsHound</span>
        </Link>
        <div className="document-actions">
          <Link className="document-action" to={`/documents/${slug}`}>
            Back to document
          </Link>
          {change ? (
            <a
              className="document-action"
              href={assetUrl(`/api/v1/documents/${slug}/patch`)}
            >
              Download patch
            </a>
          ) : null}
        </div>
      </header>
      <main className="pr-page">
        <article className="pr-review-card">
          <div className="document-meta">
            <span>Documentation change</span>
            {change ? (
              <>
                <span>{change.target_repo}</span>
                <span>{change.status.replaceAll("_", " ")}</span>
              </>
            ) : null}
          </div>
          <h1>Review the repository change</h1>
          <p className="document-summary">
            Confirm the upstream destination and inspect the patch. At publish
            time, DocsHound will write directly or automatically reuse or create
            your fork.
          </p>
          {displayError ? (
            <div className="pr-alert" role="alert">
              <strong>Could not complete the request.</strong>
              <span>{displayError}</span>
            </div>
          ) : null}
          <form className="pr-target-form" onSubmit={refreshPreview}>
            <label>
              Upstream documentation repository
              <input
                value={targetRepo}
                onChange={(event) => setTargetRepo(event.target.value)}
                required
              />
            </label>
            <label>
              File path
              <input
                value={filePath}
                onChange={(event) => setFilePath(event.target.value)}
                placeholder="Auto-detect from the repository"
              />
            </label>
            <button
              className="document-action"
              type="submit"
              disabled={submitting}
            >
              {submitting ? "Refreshing…" : "Refresh preview"}
            </button>
          </form>
          {change ? (
            <>
              <section className="pr-target-summary">
                <div>
                  <span>Upstream repository</span>
                  <strong>{change.target_repo}</strong>
                </div>
                <div>
                  <span>Write repository</span>
                  <strong>
                    {change.publish_repo || "Resolved when publishing"}
                  </strong>
                </div>
                <div>
                  <span>Base branch</span>
                  <strong>{change.base_branch}</strong>
                </div>
                <div>
                  <span>New branch</span>
                  <strong>{change.branch_name}</strong>
                </div>
                <div>
                  <span>Document path</span>
                  <strong>{change.file_path}</strong>
                </div>
                <div>
                  <span>Change type</span>
                  <strong>
                    {change.edit_action === "update_page"
                      ? "Update existing page"
                      : "Create new page"}
                  </strong>
                </div>
                <div>
                  <span>Detected from</span>
                  <strong>{change.detected_by}</strong>
                </div>
              </section>
              <section className="pr-patch-section">
                <div className="pr-section-head">
                  <div>
                    <span>Exact patch</span>
                    <h2>{change.file_path}</h2>
                  </div>
                  <span className="pr-format-pill">
                    {change.file_format.toUpperCase()}
                  </span>
                </div>
                <pre className="pr-patch">
                  <code>{change.patch}</code>
                </pre>
              </section>
              <footer className="pr-create-footer">
                <div>
                  {change.status === "created" ? (
                    <>
                      <strong>Pull request #{change.pr_number} is ready</strong>
                      <span>
                        Review it normally, then merge when the documentation is
                        correct.
                      </span>
                    </>
                  ) : change.status === "branch_ready" ? (
                    <>
                      <strong>Branch ready for an upstream pull request</strong>
                      <span>
                        DocsHound created the fork, branch, and commit. GitHub
                        needs one browser confirmation to open the upstream pull
                        request.
                      </span>
                    </>
                  ) : displayError ? (
                    <>
                      <strong>Publication needs attention</strong>
                      <span>
                        Follow the guidance above, refresh the preview, and try
                        again.
                      </span>
                    </>
                  ) : payload.write_enabled ? (
                    <>
                      <strong>Ready to publish upstream</strong>
                      <span>
                        DocsHound will choose a writable destination, create one
                        branch and commit, and open the pull request against the
                        upstream repository.
                      </span>
                    </>
                  ) : (
                    <>
                      <strong>Preview mode</strong>
                      <span>
                        Connect GitHub from the homepage with one token that can
                        read the source and publish to the destination.
                      </span>
                    </>
                  )}
                </div>
                {["created", "branch_ready"].includes(change.status) &&
                change.pr_url ? (
                  <a
                    className="document-primary-action"
                    href={change.pr_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {change.status === "branch_ready"
                      ? "Open upstream PR"
                      : "Open pull request"}
                  </a>
                ) : (
                  <button
                    className="document-primary-action"
                    type="button"
                    onClick={createPullRequest}
                    disabled={!payload.write_enabled || submitting}
                  >
                    {submitting ? "Publishing…" : "Publish upstream PR"}
                  </button>
                )}
              </footer>
            </>
          ) : null}
        </article>
      </main>
    </div>
  );
}
