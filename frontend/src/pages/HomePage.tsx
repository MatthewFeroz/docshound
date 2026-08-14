import {
  type CSSProperties,
  type FormEvent,
  useCallback,
  useEffect,
  useState,
} from "react";
import { Link } from "react-router-dom";

import { api, subscribeToRun } from "../api";
import { BrandHeader } from "../components/BrandHeader";
import { GapCard } from "../components/GapCard";
import type {
  DocumentationSource,
  GapCluster,
  Run,
  RunEvent,
  RuntimeConfig,
  SourceResolution,
} from "../types";

interface TimelineItem {
  id: string;
  icon: string;
  kind: string;
  label: string;
  detail?: string;
  meta?: string;
}

interface LiveGap {
  cluster: GapCluster;
  index: number;
}

function presentEvent(event: RunEvent, sequence: number): TimelineItem {
  const base = { id: `${event.type}-${sequence}`, icon: "●", kind: "system" };
  switch (event.type) {
    case "agent_decision":
      return {
        ...base,
        icon: "◆",
        kind: "decision",
        label: `Agent decision → ${event.action || "next step"}`,
        detail: event.reason,
      };
    case "tool_start":
      return {
        ...base,
        icon: "▸",
        kind: "tool-start",
        label: event.name || "Tool started",
      };
    case "tool_end":
      return {
        ...base,
        icon: event.error ? "✕" : "✓",
        kind: event.error ? "error" : "tool-end",
        label: event.error
          ? `${event.name || "Tool"} failed`
          : `${event.name || "Tool"} complete`,
        detail: event.error,
        meta: event.duration_ms ? `${event.duration_ms} ms` : undefined,
      };
    case "issues_fetched":
      return {
        ...base,
        icon: "◉",
        kind: "success",
        label: `${event.count || 0} issues fetched`,
      };
    case "pull_requests_fetched":
      return {
        ...base,
        icon: "✓",
        kind: "success",
        label: `${event.count || 0} merged pull requests fetched`,
      };
    case "documentation_activity_fetched":
      return {
        ...base,
        icon: "◎",
        kind: "success",
        label: `Documentation-repository activity fetched`,
        detail: `${event.repo} · ${event.issues_count || 0} issues · ${event.pull_requests_count || 0} merged PRs`,
      };
    case "docs_sources_found":
      return {
        ...base,
        icon: "◈",
        kind: "success",
        label: `${event.inspected_count ?? event.count ?? 0} documentation pages inspected`,
        detail: `${event.count || 0} relevant sources retained`,
      };
    case "gap_found":
      return {
        ...base,
        icon: "◇",
        kind: "success",
        label: "Documentation finding discovered",
      };
    case "run_completed":
      return {
        ...base,
        icon: event.status === "failed" ? "✕" : "✓",
        kind: event.status === "failed" ? "error" : "success",
        label: `Run ${event.status || "completed"}`,
      };
    default:
      return { ...base, label: event.type.replaceAll("_", " ") };
  }
}

function modelLabel(model: string): string {
  return model
    .split("/")
    .at(-1)!
    .split("-")
    .map((part) => {
      if (part === "gpt") return "GPT";
      if (part === "gemini") return "Gemini";
      return part.charAt(0).toUpperCase() + part.slice(1);
    })
    .join(" ");
}

function repositorySlug(value: string): string | null {
  const normalized = value
    .trim()
    .replace(/^https?:\/\/(?:www\.)?github\.com\//i, "")
    .replace(/^(?:www\.)?github\.com\//i, "")
    .replace(/\/$/, "");
  const [owner, rawRepo, ...extra] = normalized.split("/");
  const repository = rawRepo?.replace(/\.git$/i, "");
  if (
    extra.length > 0 ||
    !owner ||
    !repository ||
    !/^[A-Za-z0-9_.-]+$/.test(owner) ||
    !/^[A-Za-z0-9_.-]+$/.test(repository)
  ) {
    return null;
  }
  return `${owner}/${repository}`;
}

function documentationSourceLabel(source: DocumentationSource): string {
  if (source.kind === "website") return source.url || "Documentation website";
  return [source.repo, source.root].filter(Boolean).join(" / ");
}

export function HomePage() {
  const [repo, setRepo] = useState("");
  const [runId, setRunId] = useState<string | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<TimelineItem[]>([]);
  const [liveGaps, setLiveGaps] = useState<LiveGap[]>([]);
  const [starting, setStarting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [runtimeConfig, setRuntimeConfig] = useState<RuntimeConfig | null>(
    null,
  );
  const [gatewayKey, setGatewayKey] = useState("");
  const [savingGatewayKey, setSavingGatewayKey] = useState(false);
  const [gatewayKeyMessage, setGatewayKeyMessage] = useState<string | null>(
    null,
  );
  const [gatewayKeyError, setGatewayKeyError] = useState<string | null>(null);
  const [githubKey, setGitHubKey] = useState("");
  const [savingGitHubKey, setSavingGitHubKey] = useState(false);
  const [githubKeyMessage, setGitHubKeyMessage] = useState<string | null>(null);
  const [githubKeyError, setGitHubKeyError] = useState<string | null>(null);
  const [sourceResolution, setSourceResolution] =
    useState<SourceResolution | null>(null);
  const [documentationSource, setDocumentationSource] =
    useState<DocumentationSource | null>(null);
  const [resolvingSources, setResolvingSources] = useState(false);
  const [sourceError, setSourceError] = useState<string | null>(null);
  const [showSourceOverride, setShowSourceOverride] = useState(false);
  const [overrideRepo, setOverrideRepo] = useState("");
  const [overrideRoot, setOverrideRoot] = useState("");
  const [includeDocumentationActivity, setIncludeDocumentationActivity] =
    useState(true);

  useEffect(() => {
    void api
      .getRuntimeConfig()
      .then(setRuntimeConfig)
      .catch(() => undefined);
  }, []);

  async function saveGatewayKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const apiKey = gatewayKey.trim();
    if (!apiKey) {
      setGatewayKeyError("Enter a Merge Gateway API key.");
      return;
    }

    setSavingGatewayKey(true);
    setGatewayKeyMessage(null);
    setGatewayKeyError(null);
    try {
      const config = await api.setMergeGatewayApiKey(apiKey);
      setRuntimeConfig(config);
      setGatewayKey("");
      setGatewayKeyMessage("Connected for this local server session.");
    } catch (credentialError) {
      setGatewayKeyError(
        credentialError instanceof Error
          ? credentialError.message
          : "Could not save the key.",
      );
    } finally {
      setSavingGatewayKey(false);
    }
  }

  async function saveGitHubKey(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selectedRepo = repositorySlug(repo);
    if (!selectedRepo) {
      setGitHubKeyError("Paste a valid GitHub repository above first.");
      return;
    }
    const apiKey = githubKey.trim();
    if (!apiKey && !runtimeConfig?.github_configured) {
      setGitHubKeyError("Enter a fine-grained GitHub access token.");
      return;
    }

    setSavingGitHubKey(true);
    setGitHubKeyMessage(null);
    setGitHubKeyError(null);
    try {
      const config = await api.setGitHubApiKey(
        selectedRepo,
        apiKey || undefined,
      );
      setRuntimeConfig(config);
      setGitHubKey("");
      setGitHubKeyMessage(
        `Verified read access to ${config.github_verified_repo}.`,
      );
    } catch (credentialError) {
      setGitHubKeyError(
        credentialError instanceof Error
          ? credentialError.message
          : "Could not verify GitHub access.",
      );
    } finally {
      setSavingGitHubKey(false);
    }
  }

  const refreshRun = useCallback(async (id: string) => {
    try {
      setRun(await api.getRun(id));
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Could not refresh the run.",
      );
    }
  }, []);

  useEffect(() => {
    if (!runId) return;
    const unsubscribe = subscribeToRun(
      runId,
      (event) => {
        setEvents((current) => [
          ...current,
          presentEvent(event, current.length),
        ]);
        if (
          event.type === "gap_found" &&
          event.cluster &&
          event.index !== undefined
        ) {
          const cluster = event.cluster;
          const index = event.index;
          setLiveGaps((current) =>
            [
              ...current.filter((finding) => finding.index !== index),
              { cluster, index },
            ].sort((left, right) => left.index - right.index),
          );
        }
        void refreshRun(runId);
      },
      () => void refreshRun(runId),
    );
    return unsubscribe;
  }, [refreshRun, runId]);

  useEffect(() => {
    if (!runId || run?.status !== "running") return;
    const interval = window.setInterval(() => void refreshRun(runId), 2500);
    return () => window.clearInterval(interval);
  }, [refreshRun, run?.status, runId]);

  async function startRun(event: React.FormEvent) {
    event.preventDefault();
    const selectedRepo = repositorySlug(repo);
    const verifiedRepo = runtimeConfig?.github_verified_repo?.toLowerCase();
    if (!selectedRepo || verifiedRepo !== selectedRepo.toLowerCase()) {
      setError("Verify GitHub access for this repository before starting.");
      return;
    }
    if (!runtimeConfig?.llm_configured) {
      setError("Connect the model before starting.");
      return;
    }
    if (!documentationSource) {
      setError("Confirm the official documentation source before starting.");
      return;
    }
    setStarting(true);
    setError(null);
    try {
      const created = await api.createRun(
        repo,
        documentationSource,
        includeDocumentationActivity,
      );
      setRunId(created.run_id);
      setRun(null);
      setLiveGaps([]);
      setEvents([
        {
          id: "started",
          icon: "●",
          kind: "system",
          label: "Run started. Collecting issues and merged pull requests…",
          detail: `activity ${created.repo} · docs ${documentationSourceLabel(documentationSource)}`,
        },
      ]);
      await refreshRun(created.run_id);
    } catch (requestError) {
      setError(
        requestError instanceof Error
          ? requestError.message
          : "Could not start the run.",
      );
    } finally {
      setStarting(false);
    }
  }

  const persistedGaps =
    run?.top_gaps.map((cluster, index) => ({ cluster, index })) ?? [];
  const displayedGaps =
    persistedGaps.length >= liveGaps.length ? persistedGaps : liveGaps;
  const selectedRepo = repositorySlug(repo);
  const repoReady = selectedRepo !== null;
  const githubReady = Boolean(
    selectedRepo &&
    runtimeConfig?.github_configured &&
    runtimeConfig.github_verified_repo?.toLowerCase() ===
      selectedRepo.toLowerCase(),
  );
  const modelReady = Boolean(runtimeConfig?.llm_configured);
  const documentationReady = documentationSource !== null;
  const readinessCount = [
    repoReady,
    githubReady,
    documentationReady,
    modelReady,
  ].filter(Boolean).length;
  const readyToRun = readinessCount === 4;

  useEffect(() => {
    if (!githubReady || !selectedRepo) {
      setSourceResolution(null);
      setDocumentationSource(null);
      setSourceError(null);
      return;
    }

    let cancelled = false;
    setResolvingSources(true);
    setSourceError(null);
    void api
      .resolveSources(selectedRepo)
      .then((resolution) => {
        if (cancelled) return;
        setSourceResolution(resolution);
        setDocumentationSource(resolution.selected_source);
        setOverrideRepo(resolution.selected_source.repo || "");
        setOverrideRoot(resolution.selected_source.root || "");
      })
      .catch((requestError: unknown) => {
        if (cancelled) return;
        setSourceResolution(null);
        setDocumentationSource(null);
        setSourceError(
          requestError instanceof Error
            ? requestError.message
            : "Could not discover the documentation source.",
        );
      })
      .finally(() => {
        if (!cancelled) setResolvingSources(false);
      });
    return () => {
      cancelled = true;
    };
  }, [githubReady, selectedRepo]);

  function applyDocumentationOverride(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const selectedDocsRepo = repositorySlug(overrideRepo);
    if (!selectedDocsRepo) {
      setSourceError("Enter a documentation repository as owner/repository.");
      return;
    }
    const root = overrideRoot.trim().replace(/^\/+|\/+$/g, "");
    if (root.split("/").some((part) => part === "." || part === "..")) {
      setSourceError(
        "The documentation folder cannot contain . or .. segments.",
      );
      return;
    }
    setDocumentationSource({
      kind: "github",
      repo: selectedDocsRepo,
      root: root || null,
      url: null,
      confidence: 1,
      discovered_by: "user_override",
      page_count: null,
    });
    setSourceError(null);
    setShowSourceOverride(false);
  }

  return (
    <>
      <BrandHeader className="home-toolbar">
        <nav className="home-nav" aria-label="Homepage navigation">
          <a href="#overview">Product</a>
          <a href="#workflow">Workflow</a>
          <a href="#grounding">Grounding</a>
          <Link to="/findings">Findings</Link>
          <a
            className="home-github-link"
            href="https://github.com/MatthewFeroz/docshound"
            target="_blank"
            rel="noreferrer"
          >
            <svg viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 .7a11.3 11.3 0 0 0-3.57 22.02c.57.1.78-.25.78-.55v-2.2c-3.18.7-3.85-1.35-3.85-1.35-.52-1.33-1.27-1.68-1.27-1.68-1.04-.71.08-.7.08-.7 1.15.08 1.75 1.18 1.75 1.18 1.02 1.74 2.68 1.24 3.34.95.1-.74.4-1.24.73-1.53-2.54-.29-5.21-1.27-5.21-5.65 0-1.25.45-2.27 1.18-3.07-.12-.29-.51-1.45.11-3.02 0 0 .96-.31 3.11 1.17a10.8 10.8 0 0 1 5.67 0c2.16-1.48 3.1-1.17 3.1-1.17.63 1.57.24 2.73.12 3.02.73.8 1.17 1.82 1.17 3.07 0 4.39-2.68 5.35-5.23 5.64.41.36.78 1.05.78 2.12v3.2c0 .3.2.66.79.55A11.3 11.3 0 0 0 12 .7Z" />
            </svg>
            GitHub <span aria-hidden="true">↗</span>
          </a>
        </nav>
      </BrandHeader>
      <main id="run-mount">
        {!runId ? (
          <>
            <section className="hero-v2">
              <h2 className="hero-title">
                Turn{" "}
                <span
                  className="source-rotator"
                  aria-label="open issues, merged pull requests, shipped changes, and recurring questions"
                >
                  <span className="source-sizer" aria-hidden="true">
                    merged pull requests
                  </span>
                  <em
                    className="source-word"
                    style={{ "--source-index": 0 } as CSSProperties}
                    aria-hidden="true"
                  >
                    open issues
                  </em>
                  <em
                    className="source-word"
                    style={{ "--source-index": 1 } as CSSProperties}
                    aria-hidden="true"
                  >
                    merged pull requests
                  </em>
                  <em
                    className="source-word"
                    style={{ "--source-index": 2 } as CSSProperties}
                    aria-hidden="true"
                  >
                    shipped changes
                  </em>
                  <em
                    className="source-word"
                    style={{ "--source-index": 3 } as CSSProperties}
                    aria-hidden="true"
                  >
                    recurring questions
                  </em>
                </span>
                <br />
                into citeable documentation.
              </h2>
              <p className="hero-sub">
                Paste any public repo. DocsHound reviews open issues and merged
                pull requests, then drafts documentation for missing answers and
                shipped changes.
              </p>
              <form className="hero-cta-form" onSubmit={startRun}>
                <input
                  className="hero-cta-input"
                  value={repo}
                  onChange={(event) => {
                    setRepo(event.target.value);
                    setGitHubKeyMessage(null);
                    setGitHubKeyError(null);
                  }}
                  placeholder="Paste your repo — owner/repository or URL"
                  autoComplete="off"
                  required
                />
                <button
                  type="submit"
                  className="hero-cta-btn"
                  disabled={starting || !readyToRun}
                  title={
                    readyToRun
                      ? "Run DocsHound"
                      : "Complete the readiness checklist first"
                  }
                >
                  {starting ? (
                    "Starting…"
                  ) : (
                    <>
                      Run agent <span className="hero-cta-arrow">→</span>
                    </>
                  )}
                </button>
              </form>
              {error ? (
                <div className="run-error compact-error" role="alert">
                  <p>{error}</p>
                </div>
              ) : null}
              <section
                className="run-readiness"
                aria-label="Run readiness checklist"
              >
                <div className="run-readiness-head">
                  <strong>Ready to run</strong>
                  <span>{readinessCount} of 4 ready</span>
                </div>
                <div className={`readiness-row ${repoReady ? "is-ready" : ""}`}>
                  <span className="readiness-check" aria-hidden="true">
                    {repoReady ? "✓" : "1"}
                  </span>
                  <span className="readiness-copy">
                    <strong>Repository</strong>
                    <small>
                      {repoReady ? selectedRepo : "Paste a GitHub repository"}
                    </small>
                  </span>
                  <span className="readiness-state">
                    {repoReady ? "READY" : "REQUIRED"}
                  </span>
                </div>
                <details
                  className={`readiness-row readiness-connect ${
                    githubReady ? "is-ready" : ""
                  }`}
                >
                  <summary>
                    <span className="readiness-check" aria-hidden="true">
                      {githubReady ? "✓" : "2"}
                    </span>
                    <span className="readiness-copy">
                      <strong>GitHub access</strong>
                      <small>
                        {!repoReady
                          ? "Paste a repository before connecting"
                          : githubReady
                            ? `${runtimeConfig?.github_account || "GitHub"} · deep scan enabled`
                            : runtimeConfig?.github_configured
                              ? "Verify access to this repository"
                              : "Connect a read-only token"}
                      </small>
                    </span>
                    <span className="readiness-action">
                      {!repoReady
                        ? "WAITING"
                        : githubReady
                          ? "CONNECTED"
                          : "CONNECT"}
                    </span>
                  </summary>
                  <form
                    className="github-connect-panel"
                    onSubmit={saveGitHubKey}
                  >
                    <div className="github-connect-head">
                      <div>
                        <strong>GitHub repository access</strong>
                        <span>
                          Verify contents, issues, and pull-request access.
                        </span>
                      </div>
                      <span className="github-depth-badge">DEEP SCAN</span>
                    </div>
                    <label htmlFor="github-access-key">
                      Fine-grained personal access token
                    </label>
                    <input
                      id="github-access-key"
                      name="githubAccessKey"
                      type="password"
                      value={githubKey}
                      onChange={(event) => setGitHubKey(event.target.value)}
                      placeholder={
                        runtimeConfig?.github_configured
                          ? "Use the connected server token"
                          : "github_pat_…"
                      }
                      autoComplete="off"
                      spellCheck={false}
                      disabled={
                        runtimeConfig?.credential_input_enabled === false ||
                        savingGitHubKey
                      }
                    />
                    <p>
                      Use a token with read access to Contents, Issues, Pull
                      requests, and Metadata. A token entered here is sent to
                      your local backend, held only in memory, and never
                      returned to the browser.
                    </p>
                    {runtimeConfig?.credential_input_enabled === false ? (
                      <div
                        className="hero-model-feedback is-error"
                        role="alert"
                      >
                        Browser key entry is disabled in production. Configure
                        GITHUB_TOKEN on the server.
                      </div>
                    ) : null}
                    {githubKeyMessage ? (
                      <div className="hero-model-feedback" role="status">
                        {githubKeyMessage}
                      </div>
                    ) : null}
                    {githubKeyError ? (
                      <div
                        className="hero-model-feedback is-error"
                        role="alert"
                      >
                        {githubKeyError}
                      </div>
                    ) : null}
                    <div className="github-connect-actions">
                      <a
                        href="https://github.com/settings/personal-access-tokens/new"
                        target="_blank"
                        rel="noreferrer"
                      >
                        Create token ↗
                      </a>
                      <button
                        type="submit"
                        disabled={
                          !repoReady ||
                          savingGitHubKey ||
                          (runtimeConfig?.credential_input_enabled === false &&
                            !runtimeConfig.github_configured)
                        }
                      >
                        {savingGitHubKey
                          ? "Verifying…"
                          : runtimeConfig?.github_configured && !githubKey
                            ? "Verify connection"
                            : "Connect GitHub"}
                      </button>
                    </div>
                  </form>
                </details>
                <details
                  className={`readiness-row readiness-connect documentation-connect ${
                    documentationReady ? "is-ready" : ""
                  }`}
                >
                  <summary>
                    <span className="readiness-check" aria-hidden="true">
                      {documentationReady ? "✓" : "3"}
                    </span>
                    <span className="readiness-copy">
                      <strong>Official documentation</strong>
                      <small>
                        {resolvingSources
                          ? "Discovering the canonical docs repo and folder…"
                          : documentationSource
                            ? `${documentationSourceLabel(documentationSource)}${
                                documentationSource.page_count !== null
                                  ? ` · ${documentationSource.page_count} pages`
                                  : ""
                              }`
                            : githubReady
                              ? "Open to retry or choose a source"
                              : "Connect GitHub to discover it automatically"}
                      </small>
                    </span>
                    <span className="readiness-action">
                      {resolvingSources
                        ? "FINDING"
                        : documentationReady
                          ? "REVIEW"
                          : "REQUIRED"}
                    </span>
                  </summary>
                  <div className="github-connect-panel docs-source-panel">
                    <div className="github-connect-head">
                      <div>
                        <strong>Documentation source</strong>
                        <span>
                          Confirm where DocsHound reads pages and documentation
                          activity.
                        </span>
                      </div>
                      <span className="github-depth-badge">AUTO-DETECTED</span>
                    </div>
                    {documentationSource ? (
                      <div className="docs-source-current">
                        <div>
                          <strong>
                            {documentationSourceLabel(documentationSource)}
                          </strong>
                          <span>
                            {documentationSource.page_count ?? "Uncounted"}{" "}
                            pages ·{" "}
                            {documentationSource.discovered_by.replaceAll(
                              "_",
                              " ",
                            )}
                          </span>
                        </div>
                        {documentationSource.url ? (
                          <a
                            href={documentationSource.url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            Open ↗
                          </a>
                        ) : null}
                      </div>
                    ) : null}
                    {sourceResolution?.documentation_sources.length ? (
                      <label className="docs-source-choice">
                        Detected source
                        <select
                          value={sourceResolution.documentation_sources.findIndex(
                            (source) =>
                              source.repo === documentationSource?.repo &&
                              source.root === documentationSource?.root,
                          )}
                          onChange={(event) => {
                            const source =
                              sourceResolution.documentation_sources[
                                Number(event.target.value)
                              ];
                            if (source) {
                              setDocumentationSource(source);
                              setOverrideRepo(source.repo || "");
                              setOverrideRoot(source.root || "");
                            }
                          }}
                        >
                          {sourceResolution.documentation_sources.map(
                            (source, index) => (
                              <option
                                value={index}
                                key={`${source.repo}-${source.root}`}
                              >
                                {documentationSourceLabel(source)} ·{" "}
                                {source.page_count} pages
                              </option>
                            ),
                          )}
                        </select>
                      </label>
                    ) : null}
                    {documentationSource?.repo &&
                    documentationSource.repo.toLowerCase() !==
                      selectedRepo?.toLowerCase() ? (
                      <label className="docs-activity-toggle">
                        <input
                          type="checkbox"
                          checked={includeDocumentationActivity}
                          onChange={(event) =>
                            setIncludeDocumentationActivity(
                              event.target.checked,
                            )
                          }
                        />
                        <span>
                          Also analyze issues and merged PRs from{" "}
                          {documentationSource.repo}
                        </span>
                      </label>
                    ) : (
                      <p className="docs-activity-note">
                        Documentation activity is already included because the
                        pages live in the product repository.
                      </p>
                    )}
                    <button
                      className="docs-source-change"
                      type="button"
                      onClick={() =>
                        setShowSourceOverride((current) => !current)
                      }
                    >
                      {showSourceOverride ? "Cancel override" : "Change source"}
                    </button>
                    {showSourceOverride ? (
                      <form
                        className="docs-source-override"
                        onSubmit={applyDocumentationOverride}
                      >
                        <label htmlFor="documentation-repo">
                          Documentation repository
                        </label>
                        <input
                          id="documentation-repo"
                          value={overrideRepo}
                          onChange={(event) =>
                            setOverrideRepo(event.target.value)
                          }
                          placeholder="owner/documentation-repo"
                          required
                        />
                        <label htmlFor="documentation-root">
                          Documentation folder <span>optional</span>
                        </label>
                        <input
                          id="documentation-root"
                          value={overrideRoot}
                          onChange={(event) =>
                            setOverrideRoot(event.target.value)
                          }
                          placeholder="content/en/docs"
                        />
                        <button type="submit">Use this source</button>
                      </form>
                    ) : null}
                    {sourceError ? (
                      <div
                        className="hero-model-feedback is-error"
                        role="alert"
                      >
                        {sourceError}
                      </div>
                    ) : null}
                  </div>
                </details>
                <div
                  className={`readiness-row ${modelReady ? "is-ready" : ""}`}
                >
                  <span className="readiness-check" aria-hidden="true">
                    {modelReady ? "✓" : "4"}
                  </span>
                  <span className="readiness-copy">
                    <strong>Model connection</strong>
                    <small>
                      {modelReady
                        ? `${runtimeConfig?.llm_primary_model ? modelLabel(runtimeConfig.llm_primary_model) : "Gemini 3.7 Flash"} connected`
                        : "Merge Gateway key required"}
                    </small>
                  </span>
                  <button
                    className="readiness-action"
                    type="button"
                    onClick={() => {
                      const picker =
                        document.querySelector<HTMLDetailsElement>(
                          "#model-connection",
                        );
                      if (picker) {
                        picker.open = true;
                        picker.scrollIntoView({
                          behavior: "smooth",
                          block: "center",
                        });
                      }
                    }}
                  >
                    {modelReady ? "READY" : "CONFIGURE"}
                  </button>
                </div>
              </section>
              <details className="hero-model-picker" id="model-connection">
                <summary>
                  <span
                    className={`hero-model-status ${
                      runtimeConfig?.llm_configured ? "is-connected" : ""
                    }`}
                  />
                  <span className="hero-model-name">
                    {runtimeConfig?.llm_primary_model
                      ? modelLabel(runtimeConfig.llm_primary_model)
                      : "Gemini 3.7 Flash"}
                  </span>
                  <span className="hero-model-via">via Merge Gateway</span>
                  <span className="hero-model-chevron" aria-hidden="true">
                    ▾
                  </span>
                </summary>
                <form className="hero-model-menu" onSubmit={saveGatewayKey}>
                  <div className="hero-model-menu-head">
                    <div>
                      <strong>Model connection</strong>
                      <span>
                        {runtimeConfig?.llm_configured
                          ? "Connected"
                          : "API key required"}
                      </span>
                    </div>
                    <span
                      className={`hero-model-badge ${
                        runtimeConfig?.llm_configured ? "is-connected" : ""
                      }`}
                    >
                      {runtimeConfig?.llm_configured ? "READY" : "SETUP"}
                    </span>
                  </div>
                  <label htmlFor="merge-gateway-key">
                    Merge Gateway API key
                  </label>
                  <input
                    id="merge-gateway-key"
                    name="mergeGatewayApiKey"
                    type="password"
                    value={gatewayKey}
                    onChange={(event) => setGatewayKey(event.target.value)}
                    placeholder="Enter your key"
                    autoComplete="off"
                    spellCheck={false}
                    disabled={
                      runtimeConfig?.credential_input_enabled === false ||
                      savingGatewayKey
                    }
                    required
                  />
                  <p>
                    Sent to your local DocsHound backend and held only in memory
                    until the server restarts.
                  </p>
                  {runtimeConfig?.credential_input_enabled === false ? (
                    <div className="hero-model-feedback is-error" role="alert">
                      Browser key entry is disabled in production. Configure the
                      server secret instead.
                    </div>
                  ) : null}
                  {gatewayKeyMessage ? (
                    <div className="hero-model-feedback" role="status">
                      {gatewayKeyMessage}
                    </div>
                  ) : null}
                  {gatewayKeyError ? (
                    <div className="hero-model-feedback is-error" role="alert">
                      {gatewayKeyError}
                    </div>
                  ) : null}
                  <button
                    type="submit"
                    disabled={
                      runtimeConfig?.credential_input_enabled === false ||
                      savingGatewayKey
                    }
                  >
                    {savingGatewayKey ? "Connecting…" : "Save connection"}
                  </button>
                </form>
              </details>
              <div className="hero-agent-orbit" aria-hidden="true">
                <div className="hero-agent-float hero-agent-opencode">
                  <div className="hero-agent-tile">
                    <img
                      src="/logos/opencode-mark.svg"
                      alt=""
                      draggable="false"
                    />
                  </div>
                </div>
                <div className="hero-agent-float hero-agent-deepagents">
                  <div className="hero-agent-tile">
                    <img
                      src="/logos/deepagents-mark.svg"
                      alt=""
                      draggable="false"
                    />
                  </div>
                </div>
                <div className="hero-agent-float hero-agent-pi">
                  <div className="hero-agent-tile">
                    <img src="/logos/pi-mark.svg" alt="" draggable="false" />
                  </div>
                </div>
                <div className="hero-agent-float hero-agent-t3">
                  <div className="hero-agent-tile">
                    <img
                      src="/logos/t3-code-mark.svg"
                      alt=""
                      draggable="false"
                    />
                  </div>
                </div>
              </div>
              <aside
                className="hero-floater hero-floater-left"
                aria-hidden="true"
              >
                <div className="floater-card">
                  <div className="floater-kicker">
                    <span className="floater-sev floater-sev-high">HIGH</span>
                    <span className="floater-repo">acme/sdk-python</span>
                  </div>
                  <div className="floater-title">
                    Async tracing not propagating across tasks
                  </div>
                  <div className="floater-question">
                    &quot;Why are my async spans missing?&quot;
                  </div>
                  <div className="floater-meta">
                    12 issues clustered · 4s ago
                  </div>
                </div>
              </aside>
              <aside
                className="hero-floater hero-floater-right"
                aria-hidden="true"
              >
                <div className="floater-card">
                  <div className="floater-kicker">
                    <span className="floater-status">APPROVED</span>
                    <span className="floater-repo">Markdown document</span>
                  </div>
                  <div className="floater-title">
                    Tracing async generators in 3 steps
                  </div>
                  <div className="floater-question">
                    Ready to copy into any documentation system
                  </div>
                  <div className="floater-meta">Draft → review → approve</div>
                </div>
              </aside>
            </section>
            <ProductPreview />
            <HomeOverview />
          </>
        ) : (
          <section className="run-panel">
            <section className="panel timeline-panel">
              <header className="panel-head">
                <h2>Agent Timeline</h2>
                <span className="panel-sub">
                  run <code>{runId.slice(0, 8)}</code>
                </span>
              </header>
              {run?.documentation_source ? (
                <div className="run-depth-summary">
                  <div>
                    <span>Product activity</span>
                    <strong>
                      {Math.max(
                        0,
                        run.issues_scraped - run.documentation_issues_scraped,
                      )}{" "}
                      issues ·{" "}
                      {Math.max(
                        0,
                        run.pull_requests_scraped -
                          run.documentation_pull_requests_scraped,
                      )}{" "}
                      PRs
                    </strong>
                  </div>
                  <div>
                    <span>Official docs</span>
                    <strong>
                      {run.docs_candidates_inspected} of{" "}
                      {run.documentation_source.page_count ?? "?"} pages read
                    </strong>
                  </div>
                  <div>
                    <span>Docs activity</span>
                    <strong>
                      {run.documentation_issues_scraped} issues ·{" "}
                      {run.documentation_pull_requests_scraped} PRs
                    </strong>
                  </div>
                </div>
              ) : null}
              <ol className="timeline">
                {events.map((item) => (
                  <li key={item.id} className={`event kind-${item.kind}`}>
                    <span className="event-icon">{item.icon}</span>
                    <div className="event-body">
                      <div className="event-label">{item.label}</div>
                      {item.detail ? (
                        <div className="event-detail">{item.detail}</div>
                      ) : null}
                    </div>
                    {item.meta ? (
                      <span className="event-meta">{item.meta}</span>
                    ) : null}
                  </li>
                ))}
              </ol>
              {error ? (
                <div className="run-error compact-error" role="alert">
                  <p>{error}</p>
                </div>
              ) : null}
            </section>
            <section className="panel gaps-panel">
              <header className="panel-head">
                <h2>Gaps Discovered</h2>
                <span className="panel-sub">{displayedGaps.length} found</span>
              </header>
              <div className="gaps">
                {displayedGaps.length ? (
                  displayedGaps.map(({ cluster, index }) => (
                    <GapCard
                      key={`${cluster.name}-${index}`}
                      cluster={cluster}
                      index={index}
                      runId={runId}
                    />
                  ))
                ) : (
                  <div className="gaps-empty">
                    Analysis is in progress. The first findings can take 15–30
                    seconds to appear.
                  </div>
                )}
              </div>
            </section>
          </section>
        )}
      </main>
    </>
  );
}

function ProductPreview() {
  const timeline = [
    ["✓", "Repository research complete", "42 issues · 18 merged PRs"],
    ["✓", "9 documentation needs clustered", "5 gaps · 4 shipped changes"],
    ["◆", "Agent decision → search_docs", "Check coverage before drafting"],
    ["◈", "3 documentation sources checked", "Canonical English pages"],
  ];

  return (
    <section className="home-product-section" id="overview">
      <div className="home-section-heading">
        <span>THE PRODUCT</span>
        <h2>See the evidence, the decisions, and the draft in one place.</h2>
        <p>
          A live agent timeline sits beside the finding it produced, so every
          proposed documentation change remains explainable and reviewable.
        </p>
      </div>

      <div
        className="home-product-window"
        aria-label="DocsHound product preview"
      >
        <div className="home-window-toolbar">
          <div className="home-window-dots" aria-hidden="true">
            <span />
            <span />
            <span />
          </div>
          <div className="home-window-title">
            <img src="/logos/docshound.png" alt="" />
            <strong>DocsHound</strong>
            <code>anomalyco/opencode</code>
          </div>
          <span className="home-window-live">
            <i /> running
          </span>
        </div>

        <div className="home-product-body">
          <aside className="home-preview-timeline">
            <header>
              <span>Agent timeline</span>
              <code>run 7f21a9c4</code>
            </header>
            <ol>
              {timeline.map(([icon, title, detail], index) => (
                <li className={index === 2 ? "is-active" : ""} key={title}>
                  <span>{icon}</span>
                  <div>
                    <strong>{title}</strong>
                    <small>{detail}</small>
                  </div>
                  <code>
                    {index === 2 ? "now" : `${index + 1}.${index + 4}s`}
                  </code>
                </li>
              ))}
            </ol>
            <div className="home-preview-route">
              <span>MODEL ROUTE</span>
              <strong>Gemini 3.7 Flash</strong>
              <small>via Merge Gateway</small>
            </div>
          </aside>

          <article className="home-preview-finding">
            <div className="home-preview-topline">
              <span className="home-preview-severity">HIGH</span>
              <span>SHIPPED CHANGE</span>
              <span>94% confidence</span>
            </div>
            <h3>Webhook retry behavior</h3>
            <p className="home-preview-question">
              “How does exponential backoff work after a failed delivery?”
            </p>

            <div className="home-preview-coverage">
              <div>
                <span>Documentation coverage</span>
                <strong>Related page needs an update</strong>
              </div>
              <code>PARTIAL</code>
            </div>

            <div className="home-preview-evidence">
              <span>REPOSITORY EVIDENCE</span>
              <div>
                <strong>#842 Webhook delivery retries</strong>
                <small>open · 14 comments</small>
              </div>
              <div>
                <strong>PR #791 Add exponential backoff</strong>
                <small>merged · source linked</small>
              </div>
              <div>
                <strong>Webhook delivery guide</strong>
                <small>guides/webhooks.mdx</small>
              </div>
            </div>

            <div className="home-preview-draft">
              <span>HUMAN REVIEW DRAFT</span>
              <strong>Configure webhook retries</strong>
              <p>
                Failed deliveries are retried with exponential backoff. Each
                attempt preserves the original event payload…
              </p>
            </div>

            <footer className="home-preview-actions">
              <span>Reject</span>
              <strong>Approve and open →</strong>
            </footer>
          </article>
        </div>
      </div>

      <div className="home-product-proof" aria-label="Product capabilities">
        <span>Live SSE progress</span>
        <span>Repository-backed evidence</span>
        <span>Editable Markdown</span>
        <span>Exact PR patch</span>
      </div>
    </section>
  );
}

function HomeOverview() {
  const steps = [
    ["Research", "GitHub", "Collect open issues and merged pull requests."],
    ["Analyze", "Agent", "Group recurring questions and shipped changes."],
    ["Check docs", "Search", "Classify existing coverage before writing."],
    ["Draft", "Markdown", "Write only the missing or outdated guidance."],
    ["Review + publish", "Human", "Approve an exact repository patch and PR."],
  ];

  return (
    <div className="home-overview">
      <section className="home-workflow-section" id="workflow">
        <div className="home-section-heading home-heading-split">
          <div>
            <span>HOW IT WORKS</span>
            <h2>From noisy repository activity to one useful docs change.</h2>
          </div>
          <p>
            DocsHound follows an explicit sequence with a recorded decision
            between every stage. The workflow can explain why it searched,
            drafted, skipped, or stopped.
          </p>
        </div>

        <ol className="home-workflow-grid">
          {steps.map(([title, tool, detail], index) => (
            <li key={title}>
              <span>{String(index + 1).padStart(2, "0")}</span>
              <code>{tool}</code>
              <h3>{title}</h3>
              <p>{detail}</p>
            </li>
          ))}
        </ol>
      </section>

      <section className="home-grounding-section" id="grounding">
        <div className="home-grounding-copy">
          <span>GROUNDING</span>
          <h2>Search first. Draft second.</h2>
          <p>
            A GitHub question is not automatically a documentation gap.
            DocsHound searches canonical first-party pages, excludes unrelated
            package READMEs, and writes only the delta.
          </p>
          <ul>
            <li>
              <i className="is-missing" />
              <div>
                <strong>Missing</strong>
                <small>Create a focused new page</small>
              </div>
            </li>
            <li>
              <i className="is-partial" />
              <div>
                <strong>Partial</strong>
                <small>Update the relevant existing page</small>
              </div>
            </li>
            <li>
              <i className="is-documented" />
              <div>
                <strong>Documented</strong>
                <small>Keep the audit trail and skip the draft</small>
              </div>
            </li>
          </ul>
        </div>

        <div className="home-grounding-panel">
          <header>
            <span>EVIDENCE PACKET</span>
            <code>3 linked sources</code>
          </header>
          <div className="home-grounding-source">
            <span>ISSUE</span>
            <div>
              <strong>#842 Webhook delivery retries</strong>
              <small>Recurring user question</small>
            </div>
          </div>
          <div className="home-grounding-source">
            <span className="is-pr">PR</span>
            <div>
              <strong>#791 Add exponential backoff</strong>
              <small>Confirmed shipped behavior</small>
            </div>
          </div>
          <div className="home-grounding-source">
            <span className="is-doc">DOC</span>
            <div>
              <strong>Webhook delivery guide</strong>
              <small>Canonical English page · partial coverage</small>
            </div>
          </div>
          <div className="home-grounding-result">
            <span>RECOMMENDED ACTION</span>
            <strong>Update guides/webhooks.mdx</strong>
            <code>update_page</code>
          </div>
        </div>
      </section>

      <section className="home-controls-section">
        <div className="home-section-heading">
          <span>CONTROL + CONFIDENCE</span>
          <h2>The agent proposes. A person publishes.</h2>
          <p>
            The generation is useful because every output stays inspectable from
            source evidence through the final GitHub pull request.
          </p>
        </div>
        <div className="home-control-grid">
          <article>
            <span>01</span>
            <h3>Evidence attached</h3>
            <p>
              Issues, merged changes, and relevant docs travel with the draft.
            </p>
          </article>
          <article>
            <span>02</span>
            <h3>Human approval gate</h3>
            <p>Edit, approve, or reject before any repository write occurs.</p>
          </article>
          <article>
            <span>03</span>
            <h3>Exact patch preview</h3>
            <p>
              Inspect the target path, format, branch, and diff before the PR.
            </p>
          </article>
          <article>
            <span>04</span>
            <h3>Traceable end to end</h3>
            <p>OpenTelemetry records agent, tool, and model spans safely.</p>
          </article>
        </div>
      </section>

      <section className="home-final-cta">
        <img src="/logos/docshound.png" alt="" />
        <span>FROM SIGNAL TO SOURCE OF TRUTH</span>
        <h2>Let the repository tell you what the docs are missing.</h2>
        <p>
          Paste a public GitHub repository and watch DocsHound show its work.
        </p>
        <div>
          <a className="home-final-primary" href="#run-mount">
            Run DocsHound ↑
          </a>
          <Link className="home-final-secondary" to="/findings">
            Browse findings
          </Link>
        </div>
      </section>
    </div>
  );
}
