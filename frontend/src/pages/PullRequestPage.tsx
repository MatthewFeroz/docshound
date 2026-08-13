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
            Confirm where the approved document belongs, inspect the patch, and
            create a normal documentation pull request.
          </p>
          {error ? (
            <div className="pr-alert" role="alert">
              <strong>Could not complete the request.</strong>
              <span>{error}</span>
            </div>
          ) : null}
          <form className="pr-target-form" onSubmit={refreshPreview}>
            <label>
              Documentation repository
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
                  ) : payload.write_enabled ? (
                    <>
                      <strong>Ready to create the pull request</strong>
                      <span>
                        This creates one branch, one documentation commit, and
                        one pull request.
                      </span>
                    </>
                  ) : (
                    <>
                      <strong>Preview mode</strong>
                      <span>
                        Connect repository write access to enable the final
                        create step.
                      </span>
                    </>
                  )}
                </div>
                {change.status === "created" && change.pr_url ? (
                  <a
                    className="document-primary-action"
                    href={change.pr_url}
                    target="_blank"
                    rel="noreferrer"
                  >
                    Open pull request
                  </a>
                ) : (
                  <button
                    className="document-primary-action"
                    type="button"
                    onClick={createPullRequest}
                    disabled={!payload.write_enabled || submitting}
                  >
                    {submitting ? "Creating…" : "Create documentation PR"}
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
