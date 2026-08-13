import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

import { api, subscribeToRun } from "../api";
import { BrandHeader } from "../components/BrandHeader";
import { GapCard } from "../components/GapCard";
import type { GapCluster, Run, RunEvent, RuntimeConfig } from "../types";

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
    case "docs_sources_found":
      return {
        ...base,
        icon: "◈",
        kind: "success",
        label: `${event.count || 0} documentation sources checked`,
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

  useEffect(() => {
    void api
      .getRuntimeConfig()
      .then(setRuntimeConfig)
      .catch(() => undefined);
  }, []);

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
    setStarting(true);
    setError(null);
    try {
      const created = await api.createRun(repo);
      setRunId(created.run_id);
      setRun(null);
      setLiveGaps([]);
      setEvents([
        {
          id: "started",
          icon: "●",
          kind: "system",
          label: "Run started. Collecting issues and merged pull requests…",
          detail: `repo ${created.repo}`,
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

  return (
    <>
      <BrandHeader tagline="Repository activity → reviewed documentation">
        <div className="top-actions">
          <Link className="showcase-link" to="/showcase">
            Product tour
          </Link>
          <Link className="published-link" to="/findings">
            Browse findings →
          </Link>
        </div>
      </BrandHeader>
      <main id="run-mount">
        {!runId ? (
          <>
            <section className="hero-v2">
              <h2 className="hero-title">
                Turn <em>repository activity</em>
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
                  onChange={(event) => setRepo(event.target.value)}
                  placeholder="Paste your repo — owner/repository or URL"
                  autoComplete="off"
                  required
                />
                <button
                  type="submit"
                  className="hero-cta-btn"
                  disabled={starting}
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
              <div className="hero-trust">
                <span className="hero-trust-dot" />
                <span>Live now</span>
                <span className="hero-trust-sep">·</span>
                <span>Real repository evidence</span>
                {runtimeConfig?.llm_primary_model ? (
                  <>
                    <span className="hero-trust-sep">·</span>
                    <span>
                      {modelLabel(runtimeConfig.llm_primary_model)}
                      {runtimeConfig.llm_gateway === "merge"
                        ? " via Merge Gateway"
                        : ""}
                      {runtimeConfig.llm_fallback_model
                        ? ` · ${modelLabel(runtimeConfig.llm_fallback_model)} fallback`
                        : ""}
                    </span>
                  </>
                ) : null}
              </div>
            </section>
            <HowItWorks />
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

function HowItWorks() {
  const steps = [
    ["Collect", "issues and merged pull requests from a public repository"],
    ["Identify", "open gaps and shipped changes that need documentation"],
    ["Check", "the existing documentation for coverage and evidence"],
    ["Draft", "a citeable answer for human review"],
    ["Publish", "approved Markdown through a documentation pull request"],
  ];
  return (
    <section className="placeholder">
      <div className="hero">
        <div className="hero-card">
          <span className="hero-eyebrow">How it works</span>
          <h2>
            From <em>repository activity</em> to citeable documentation.
          </h2>
          <p className="hero-lede">
            DocsHound checks recent repository activity, finds missing answers,
            and drafts grounded guidance for review.
          </p>
          <ul className="hero-steps">
            {steps.map(([title, detail], index) => (
              <li key={title}>
                <span className="step-num">{index + 1}</span>
                <span>
                  <strong>{title}</strong> {detail}
                </span>
              </li>
            ))}
          </ul>
        </div>
        <aside className="hero-flow" aria-label="Pipeline preview">
          <div className="flow-title">Pipeline preview</div>
          {steps.map(([title, detail], index) => (
            <div className="flow-step" key={title}>
              <div className="flow-icon">
                <span>{index + 1}</span>
              </div>
              <div className="flow-body">
                <div className="flow-name">{title}</div>
                <div className="flow-detail">{detail}</div>
              </div>
            </div>
          ))}
        </aside>
      </div>
    </section>
  );
}
