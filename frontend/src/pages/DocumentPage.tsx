import { useEffect, useState } from "react";
import ReactMarkdown from "react-markdown";
import { Link, useNavigate, useParams } from "react-router-dom";
import remarkGfm from "remark-gfm";

import { api, assetUrl } from "../api";
import { ErrorMessage, Loading } from "../components/Status";
import type { DocumentPayload } from "../types";

export function DocumentPage() {
  const { slug = "" } = useParams();
  const navigate = useNavigate();
  const [payload, setPayload] = useState<DocumentPayload | null>(null);
  const [view, setView] = useState<"rendered" | "markdown">("rendered");
  const [targetRepo, setTargetRepo] = useState("");
  const [filePath, setFilePath] = useState("");
  const [toast, setToast] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    api
      .getDocument(slug)
      .then((loaded) => {
        setPayload(loaded);
        setTargetRepo(
          loaded.documentation_change?.target_repo ||
            loaded.suggested_target_repo ||
            loaded.document.repo,
        );
        setFilePath(
          loaded.documentation_change?.file_path ||
            loaded.suggested_file_path ||
            "",
        );
      })
      .catch((requestError: unknown) =>
        setError(
          requestError instanceof Error
            ? requestError.message
            : "Could not load the document.",
        ),
      );
  }, [slug]);

  async function copyMarkdown() {
    if (!payload) return;
    try {
      await navigator.clipboard.writeText(payload.document.markdown);
      setToast("Markdown copied");
    } catch {
      setView("markdown");
      setToast("Select the Markdown and copy it manually");
    }
    window.setTimeout(() => setToast(""), 2200);
  }

  async function preview(event: React.FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    setError(null);
    try {
      await api.previewPullRequest(slug, targetRepo, filePath);
      navigate(`/documents/${slug}/pull-request`);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Could not prepare the change.",
      );
    } finally {
      setSubmitting(false);
    }
  }

  if (error && !payload)
    return (
      <main className="document-shell document-page">
        <ErrorMessage message={error} />
      </main>
    );
  if (!payload) return <Loading label="Loading document…" />;
  const { document, documentation_change: change } = payload;

  return (
    <div className="document-shell">
      <header className="document-toolbar">
        <Link className="document-brand" to="/">
          <img src="/logos/docshound.png" alt="" />
          <span>DocsHound</span>
        </Link>
        <div className="document-actions">
          <button
            type="button"
            className="document-action"
            onClick={copyMarkdown}
          >
            Copy Markdown
          </button>
          <a
            className="document-action"
            href={assetUrl(`/api/v1/documents/${slug}/download`)}
          >
            Download .md
          </a>
        </div>
      </header>
      <main className="document-page">
        <article className="document-paper">
          <div className="document-meta">
            <span>Approved document</span>
            <span>{document.repo}</span>
            <span>{document.approved_at.slice(0, 10)}</span>
          </div>
          <h1>{document.title}</h1>
          {document.summary ? (
            <p className="document-summary">{document.summary}</p>
          ) : null}
          <nav className="document-tabs" aria-label="Document view">
            <button
              type="button"
              className={`document-tab ${view === "rendered" ? "active" : ""}`}
              onClick={() => setView("rendered")}
            >
              Rendered
            </button>
            <button
              type="button"
              className={`document-tab ${view === "markdown" ? "active" : ""}`}
              onClick={() => setView("markdown")}
            >
              Markdown
            </button>
          </nav>
          {view === "rendered" ? (
            <section className="document-content">
              <ReactMarkdown
                remarkPlugins={[remarkGfm]}
                components={{
                  a: ({ node: _node, ...props }) => (
                    <a {...props} target="_blank" rel="noreferrer" />
                  ),
                }}
              >
                {payload.body_markdown}
              </ReactMarkdown>
            </section>
          ) : (
            <section className="document-raw">
              <textarea
                readOnly
                value={document.markdown}
                aria-label="Raw Markdown"
              />
            </section>
          )}
          {document.source_issues.length ? (
            <footer className="document-sources">
              <strong>Repository sources</strong>
              {document.source_issues.map((source) => (
                <a
                  href={source.url}
                  target="_blank"
                  rel="noreferrer"
                  key={`${source.repo}-${source.kind}-${source.number}`}
                >
                  {source.repo ? `${source.repo} · ` : ""}
                  {source.kind === "pull_request" ? "Merged PR" : "Issue"} #
                  {source.number} {source.title}
                </a>
              ))}
            </footer>
          ) : null}
          <section className="document-export">
            <div>
              <span className="document-export-kicker">Next step</span>
              {change?.status === "created" ? (
                <>
                  <h2>Documentation pull request created</h2>
                  <p>
                    The approved page is ready for repository review and merge.
                  </p>
                </>
              ) : change?.status === "branch_ready" ? (
                <>
                  <h2>Documentation branch ready</h2>
                  <p>
                    The fork, branch, and commit are ready. Confirm the upstream
                    pull request on GitHub.
                  </p>
                </>
              ) : change ? (
                <>
                  <h2>Documentation change prepared</h2>
                  <p>
                    Review the target file and exact patch before creating the
                    pull request.
                  </p>
                </>
              ) : (
                <>
                  <h2>
                    {payload.suggested_action === "update_page"
                      ? "Update the relevant documentation page"
                      : "Send this to the documentation repository"}
                  </h2>
                  <p>
                    {payload.suggested_action === "update_page"
                      ? "DocsHound found a related page and will preserve its existing content while adding this focused section."
                      : "DocsHound will detect the repository structure, choose Markdown or MDX, and prepare an exact patch."}
                  </p>
                </>
              )}
            </div>
            {change &&
            ["created", "branch_ready"].includes(change.status) &&
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
            ) : change ? (
              <Link
                className="document-primary-action"
                to={`/documents/${slug}/pull-request`}
              >
                Review change
              </Link>
            ) : (
              <form className="document-export-form" onSubmit={preview}>
                <label>
                  Upstream documentation repository
                  <input
                    value={targetRepo}
                    onChange={(event) => setTargetRepo(event.target.value)}
                    required
                  />
                </label>
                <p>
                  DocsHound will write directly when allowed, otherwise it will
                  automatically reuse or create your fork when you publish.
                </p>
                <label>
                  File path <span>optional</span>
                  <input
                    value={filePath}
                    onChange={(event) => setFilePath(event.target.value)}
                    placeholder="Auto-detect from the repository"
                  />
                </label>
                <button
                  className="document-primary-action"
                  type="submit"
                  disabled={submitting}
                >
                  {submitting ? "Preparing…" : "Prepare documentation PR"}
                </button>
              </form>
            )}
          </section>
          {error ? (
            <div className="pr-alert" role="alert">
              {error}
            </div>
          ) : null}
        </article>
      </main>
      <div
        className={`copy-toast ${toast ? "show" : ""}`}
        role="status"
        aria-live="polite"
      >
        {toast}
      </div>
    </div>
  );
}
