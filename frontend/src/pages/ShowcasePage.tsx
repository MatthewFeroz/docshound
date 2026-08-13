import { useState } from "react";
import { Link } from "react-router-dom";

type PipelineStep = {
  key: string;
  label: string;
  tool: string;
  summary: string;
  detail: string;
  output: string;
};

const pipeline: PipelineStep[] = [
  {
    key: "research",
    label: "Research",
    tool: "research_repo + research_pull_requests",
    summary: "Collect the user signals already living in GitHub.",
    detail:
      "DocsHound reads open issues and merged pull requests so it sees both unanswered questions and changes that have already shipped.",
    output: "Issues + merged PRs",
  },
  {
    key: "analyze",
    label: "Analyze",
    tool: "cluster_issues",
    summary: "Turn noisy activity into coherent documentation needs.",
    detail:
      "The agent groups recurring questions, detects shipped changes, assigns severity, and preserves the exact issue and pull request IDs behind every finding.",
    output: "Evidence-backed clusters",
  },
  {
    key: "search",
    label: "Check docs",
    tool: "search_official_docs",
    summary: "Verify what the first-party documentation already says.",
    detail:
      "Relevant documentation pages are searched before drafting. Each finding is classified as missing, partial, documented, or unable to verify.",
    output: "Coverage + source pages",
  },
  {
    key: "draft",
    label: "Draft",
    tool: "draft_review_documents",
    summary: "Write only the documentation that is actually needed.",
    detail:
      "Missing coverage becomes a new-page proposal; partial coverage becomes a focused update. Fully documented findings remain visible for the audit trail but skip drafting.",
    output: "Grounded Markdown",
  },
  {
    key: "publish",
    label: "Review + publish",
    tool: "human approval + GitHub write path",
    summary: "Keep people in control of what reaches the docs repository.",
    detail:
      "A reviewer edits, approves, or rejects the Markdown. DocsHound then detects the target docs framework, previews an exact patch, and creates a pull request only after approval.",
    output: "Reviewable docs PR",
  },
];

const traceRows = [
  { name: "docshound.agent", kind: "AGENT", time: "12.8s", depth: 0 },
  { name: "llm_decide", kind: "LLM", time: "482ms", depth: 1 },
  { name: "research_repo", kind: "TOOL", time: "1.2s", depth: 1 },
  { name: "research_pull_requests", kind: "TOOL", time: "814ms", depth: 1 },
  { name: "cluster_issues", kind: "TOOL", time: "3.4s", depth: 1 },
  { name: "search_official_docs", kind: "TOOL", time: "2.1s", depth: 1 },
  { name: "draft_review_documents", kind: "TOOL", time: "4.3s", depth: 1 },
];

export function ShowcasePage() {
  const [activeStep, setActiveStep] = useState(0);
  const step = pipeline[activeStep];

  return (
    <div className="showcase-page">
      <header className="showcase-nav">
        <Link className="showcase-brand" to="/" aria-label="DocsHound home">
          <img src="/logos/docshound.png" alt="" />
          <span>
            <strong>
              Docs<span>Hound</span>
            </strong>
            <small>Product overview</small>
          </span>
        </Link>
        <nav className="showcase-nav-links" aria-label="Showcase navigation">
          <a href="#workflow">Workflow</a>
          <a href="#grounding">Grounding</a>
          <a href="#observability">Observability</a>
          <Link className="showcase-nav-cta" to="/">
            Open the product <span aria-hidden="true">↗</span>
          </Link>
        </nav>
      </header>

      <main className="showcase-main">
        <section className="showcase-hero" id="top">
          <div className="showcase-hero-copy">
            <div className="showcase-eyebrow">
              <span className="showcase-live-dot" /> LangGraph in production
            </div>
            <h1>
              Documentation that keeps up with <em>what you ship.</em>
            </h1>
            <p>
              DocsHound turns the questions and product changes hiding in GitHub
              into grounded, reviewable documentation—without asking a model to
              guess what is true.
            </p>
            <div className="showcase-hero-actions">
              <a className="showcase-primary-action" href="#workflow">
                Explore the agent <span aria-hidden="true">↓</span>
              </a>
              <Link className="showcase-secondary-action" to="/">
                Run DocsHound
              </Link>
            </div>
            <div className="showcase-hero-proof">
              <span>Evidence first</span>
              <span>Human approved</span>
              <span>Traceable end to end</span>
            </div>
          </div>

          <div
            className="showcase-agent-window"
            aria-label="Example DocsHound run"
          >
            <div className="showcase-window-bar">
              <div className="showcase-window-dots" aria-hidden="true">
                <span />
                <span />
                <span />
              </div>
              <code>run / acme-platform/sdk</code>
              <span className="showcase-running">
                <i /> live
              </span>
            </div>
            <div className="showcase-window-body">
              <div className="showcase-run-heading">
                <span>Agent timeline</span>
                <code>7f21a9c4</code>
              </div>
              <ol className="showcase-timeline">
                <li className="is-complete">
                  <span>✓</span>
                  <div>
                    <strong>Repository research complete</strong>
                    <small>42 issues · 18 merged pull requests</small>
                  </div>
                  <code>1.8s</code>
                </li>
                <li className="is-complete">
                  <span>✓</span>
                  <div>
                    <strong>9 documentation needs clustered</strong>
                    <small>5 open gaps · 4 shipped changes</small>
                  </div>
                  <code>3.4s</code>
                </li>
                <li className="is-active">
                  <span>◆</span>
                  <div>
                    <strong>Agent decision → search_docs</strong>
                    <small>Check first-party coverage before drafting</small>
                  </div>
                  <code>now</code>
                </li>
              </ol>
              <article className="showcase-finding-preview">
                <div className="showcase-finding-topline">
                  <span className="showcase-severity">HIGH</span>
                  <span>SHIPPED CHANGE</span>
                  <span>94% confidence</span>
                </div>
                <h2>Webhook retry behavior</h2>
                <p>
                  “How does exponential backoff work after a failed delivery?”
                </p>
                <div className="showcase-coverage-row">
                  <span>Documentation coverage</span>
                  <strong>PARTIAL · UPDATE PAGE</strong>
                </div>
              </article>
            </div>
          </div>
        </section>

        <section
          className="showcase-signal-bar"
          aria-label="DocsHound foundations"
        >
          <span>Built with</span>
          <strong>LangGraph</strong>
          <i />
          <strong>LangChain instrumentation</strong>
          <i />
          <strong>OpenInference</strong>
          <i />
          <strong>FastAPI + React</strong>
        </section>

        <section className="showcase-section showcase-intro" id="problem">
          <div className="showcase-section-heading">
            <span className="showcase-section-number">01 / THE GAP</span>
            <h2>Your roadmap moved. Your documentation didn’t.</h2>
            <p>
              The most useful documentation requests rarely arrive as neat
              tickets. They surface as repeated issue threads, support-shaped
              questions, and merged pull requests whose behavior never made it
              into the docs.
            </p>
          </div>
          <div className="showcase-signal-grid">
            <article>
              <span className="showcase-signal-icon">#</span>
              <div>
                <small>OPEN ISSUES</small>
                <h3>Questions users keep asking</h3>
                <p>
                  Recurring confusion, missing how-tos, and undocumented edge
                  cases.
                </p>
              </div>
            </article>
            <div className="showcase-signal-plus" aria-hidden="true">
              +
            </div>
            <article>
              <span className="showcase-signal-icon showcase-signal-icon-pr">
                ↗
              </span>
              <div>
                <small>MERGED PULL REQUESTS</small>
                <h3>Changes users need to understand</h3>
                <p>
                  New capabilities and changed behavior that already shipped.
                </p>
              </div>
            </article>
            <div className="showcase-signal-equals" aria-hidden="true">
              →
            </div>
            <article className="showcase-signal-result">
              <span className="showcase-signal-icon">◇</span>
              <div>
                <small>DOCSHOUND FINDINGS</small>
                <h3>A prioritized docs backlog</h3>
                <p>Every proposed change linked back to repository evidence.</p>
              </div>
            </article>
          </div>
          <div className="showcase-principles">
            <div>
              <strong>2</strong>
              <span>repository signals</span>
            </div>
            <div>
              <strong>3</strong>
              <span>actionable coverage outcomes</span>
            </div>
            <div>
              <strong>1</strong>
              <span>required human approval gate</span>
            </div>
          </div>
        </section>

        <section className="showcase-section showcase-workflow" id="workflow">
          <div className="showcase-section-heading showcase-heading-row">
            <div>
              <span className="showcase-section-number">02 / THE AGENT</span>
              <h2>A stateful loop, not a prompt chain.</h2>
            </div>
            <p>
              LangGraph gives DocsHound an explicit state machine, a decision
              point between every tool, and a durable audit trail of why the
              agent moved forward.
            </p>
          </div>

          <div
            className="showcase-graph"
            aria-label="DocsHound LangGraph workflow"
          >
            <div className="showcase-graph-router">
              <span>◆</span>
              <strong>llm_decide</strong>
              <small>guarded router</small>
            </div>
            <span className="showcase-graph-arrow" aria-hidden="true">
              →
            </span>
            {pipeline.map((item, index) => (
              <div className="showcase-graph-segment" key={item.key}>
                <button
                  type="button"
                  className={activeStep === index ? "is-active" : ""}
                  onClick={() => setActiveStep(index)}
                  aria-pressed={activeStep === index}
                >
                  <span>{String(index + 1).padStart(2, "0")}</span>
                  <strong>{item.label}</strong>
                </button>
                {index < pipeline.length - 1 ? (
                  <>
                    <span className="showcase-loop-mark" aria-hidden="true">
                      ↶
                    </span>
                    <span className="showcase-graph-arrow" aria-hidden="true">
                      →
                    </span>
                  </>
                ) : null}
              </div>
            ))}
          </div>

          <div className="showcase-step-detail" aria-live="polite">
            <div className="showcase-step-index">
              {String(activeStep + 1).padStart(2, "0")}
            </div>
            <div className="showcase-step-copy">
              <div className="showcase-detail-kicker">
                ACTIVE STAGE · {step.tool}
              </div>
              <h3>{step.summary}</h3>
              <p>{step.detail}</p>
            </div>
            <div className="showcase-step-output">
              <span>STATE OUTPUT</span>
              <strong>{step.output}</strong>
            </div>
          </div>

          <div className="showcase-agent-features">
            <article>
              <span>◆</span>
              <h3>LLM-directed</h3>
              <p>
                The router selects the next action from the live graph state and
                records a short reason for every decision.
              </p>
            </article>
            <article>
              <span>⌁</span>
              <h3>Deterministically guarded</h3>
              <p>
                A safe router enforces the valid order, catches invalid choices,
                and runs the workflow even without a model credential.
              </p>
            </article>
            <article>
              <span>◉</span>
              <h3>Progressively streamed</h3>
              <p>
                Decisions, tool timings, sources, and findings reach the UI over
                server-sent events while the graph is still running.
              </p>
            </article>
          </div>
        </section>

        <section className="showcase-section showcase-grounding" id="grounding">
          <div className="showcase-section-heading showcase-heading-row">
            <div>
              <span className="showcase-section-number">03 / GROUNDING</span>
              <h2>Search first. Draft second.</h2>
            </div>
            <p>
              DocsHound does not equate a GitHub question with a documentation
              gap. It checks the existing docs, attaches the relevant sources,
              and only writes the delta.
            </p>
          </div>

          <div className="showcase-grounding-grid">
            <div className="showcase-coverage-panel">
              <div className="showcase-panel-label">COVERAGE CLASSIFIER</div>
              <div className="showcase-coverage-option">
                <span className="coverage-dot is-missing" />
                <div>
                  <strong>Missing</strong>
                  <small>No matching first-party guidance found</small>
                </div>
                <code>create_page</code>
              </div>
              <div className="showcase-coverage-option is-selected">
                <span className="coverage-dot is-partial" />
                <div>
                  <strong>Partial</strong>
                  <small>A related page exists but misses the answer</small>
                </div>
                <code>update_page</code>
              </div>
              <div className="showcase-coverage-option">
                <span className="coverage-dot is-documented" />
                <div>
                  <strong>Documented</strong>
                  <small>Existing docs already cover the finding</small>
                </div>
                <code>no_change</code>
              </div>
            </div>

            <div className="showcase-source-panel">
              <div className="showcase-panel-label">EVIDENCE PACKET</div>
              <div className="showcase-source-tabs">
                <span className="is-active">Repository</span>
                <span>Official docs</span>
              </div>
              <div className="showcase-source-row">
                <span className="showcase-source-type">ISSUE</span>
                <strong>#842 Webhook delivery retries</strong>
                <code>open · 14 comments</code>
              </div>
              <div className="showcase-source-row">
                <span className="showcase-source-type is-pr">PR</span>
                <strong>#791 Add exponential backoff</strong>
                <code>merged</code>
              </div>
              <div className="showcase-source-row">
                <span className="showcase-source-type is-doc">DOC</span>
                <strong>Webhook delivery guide</strong>
                <code>guides/webhooks.mdx</code>
              </div>
            </div>

            <div className="showcase-draft-panel">
              <div className="showcase-panel-label">GROUNDED DRAFT</div>
              <div className="showcase-draft-title">
                <span>MD</span>
                <div>
                  <strong>Configure webhook retries</strong>
                  <small>Proposed update · guides/webhooks.mdx</small>
                </div>
              </div>
              <pre>
                <code>{`## Retry behavior\n\nFailed deliveries are retried with\nexponential backoff. Each attempt…\n\n> Based on issue #842 and PR #791`}</code>
              </pre>
              <div className="showcase-draft-foot">
                <span>3 linked sources</span>
                <strong>Ready for review →</strong>
              </div>
            </div>
          </div>
        </section>

        <section className="showcase-section showcase-review" id="review">
          <div className="showcase-review-copy">
            <span className="showcase-section-number">
              04 / HUMAN IN THE LOOP
            </span>
            <h2>The agent proposes. A person publishes.</h2>
            <p>
              Reviewers see the finding, source evidence, coverage rationale,
              and editable Markdown together. Nothing touches a documentation
              repository before an explicit approval.
            </p>
            <ol className="showcase-review-steps">
              <li>
                <span>1</span>
                <div>
                  <strong>Inspect the evidence</strong>
                  <small>
                    Issues, shipped PRs, and relevant docs remain attached.
                  </small>
                </div>
              </li>
              <li>
                <span>2</span>
                <div>
                  <strong>Edit or reject the draft</strong>
                  <small>
                    Human judgment stays in the loop at the content boundary.
                  </small>
                </div>
              </li>
              <li>
                <span>3</span>
                <div>
                  <strong>Preview the exact patch</strong>
                  <small>
                    DocsHound detects Mintlify, Docusaurus, MkDocs, or Markdown.
                  </small>
                </div>
              </li>
              <li>
                <span>4</span>
                <div>
                  <strong>Create the pull request</strong>
                  <small>
                    A normal review-and-merge workflow remains the final gate.
                  </small>
                </div>
              </li>
            </ol>
          </div>

          <div className="showcase-diff-window">
            <div className="showcase-diff-head">
              <span>Documentation change</span>
              <code>guides/webhooks.mdx</code>
              <strong>+12</strong>
            </div>
            <div className="showcase-diff-body">
              <div>
                <span>41</span>
                <code>## Delivery behavior</code>
              </div>
              <div>
                <span>42</span>
                <code>Webhooks are delivered asynchronously.</code>
              </div>
              <div className="is-added">
                <span>43</span>
                <code>+ ## Retry behavior</code>
              </div>
              <div className="is-added">
                <span>44</span>
                <code>+</code>
              </div>
              <div className="is-added">
                <span>45</span>
                <code>+ Failed deliveries use exponential backoff.</code>
              </div>
              <div className="is-added">
                <span>46</span>
                <code>+ Retry attempts preserve the event payload.</code>
              </div>
              <div className="is-added">
                <span>47</span>
                <code>+</code>
              </div>
              <div className="is-added">
                <span>48</span>
                <code>+ See the delivery log for attempt history.</code>
              </div>
            </div>
            <div className="showcase-diff-footer">
              <span>Branch · docs/configure-webhook-retries</span>
              <span className="showcase-diff-action">
                Create pull request ↗
              </span>
            </div>
          </div>
        </section>

        <section
          className="showcase-section showcase-observability"
          id="observability"
        >
          <div className="showcase-section-heading showcase-heading-row">
            <div>
              <span className="showcase-section-number">
                05 / OBSERVABILITY
              </span>
              <h2>Every run leaves a useful trail.</h2>
            </div>
            <p>
              OpenInference semantics and OpenTelemetry export make the whole
              agent legible—from the root run to every tool and model call. The
              same lifecycle events power the live product UI.
            </p>
          </div>

          <div className="showcase-trace-card">
            <div className="showcase-trace-toolbar">
              <div>
                <span className="showcase-live-dot" /> TRACE
                <strong>docshound.agent</strong>
              </div>
              <div>
                <code>run_id: 7f21a9c4</code>
                <code>repo: acme-platform/sdk</code>
              </div>
            </div>
            <div className="showcase-trace-headings">
              <span>SPAN</span>
              <span>KIND</span>
              <span>DURATION</span>
            </div>
            <div className="showcase-trace-list">
              {traceRows.map((row, index) => (
                <div className="showcase-trace-row" key={row.name}>
                  <div style={{ paddingLeft: `${row.depth * 22}px` }}>
                    <span className={index === 0 ? "is-root" : ""} />
                    <strong>{row.name}</strong>
                  </div>
                  <code className={`is-${row.kind.toLowerCase()}`}>
                    {row.kind}
                  </code>
                  <span>{row.time}</span>
                </div>
              ))}
            </div>
            <div className="showcase-trace-meta">
              <div>
                <span>MODEL ROUTING</span>
                <strong>Merge Gateway · primary + fallback</strong>
              </div>
              <div>
                <span>SAFE ATTRIBUTES</span>
                <strong>Counts, timings, provider, model</strong>
              </div>
              <div>
                <span>CONTENT POLICY</span>
                <strong>Repository bodies excluded from custom spans</strong>
              </div>
            </div>
          </div>
        </section>

        <section
          className="showcase-section showcase-architecture"
          id="architecture"
        >
          <div className="showcase-section-heading">
            <span className="showcase-section-number">06 / UNDER THE HOOD</span>
            <h2>Small surface. Clear boundaries.</h2>
            <p>
              DocsHound is split into two independently deployable applications.
              The browser gets a typed product API; credentials and write access
              stay behind the backend boundary.
            </p>
          </div>
          <div className="showcase-architecture-grid">
            <article>
              <div className="showcase-architecture-top">
                <span>01</span>
                <code>frontend/</code>
              </div>
              <h3>Review experience</h3>
              <p>
                React + TypeScript turns SSE events into a live agent timeline,
                finding review, document editor, and patch preview.
              </p>
              <div className="showcase-tech-list">
                <span>Vite</span>
                <span>React 19</span>
                <span>Typed API client</span>
                <span>SSE</span>
              </div>
            </article>
            <article>
              <div className="showcase-architecture-top">
                <span>02</span>
                <code>backend/</code>
              </div>
              <h3>Agent runtime</h3>
              <p>
                FastAPI owns the LangGraph state machine, GitHub and docs tools,
                model routing, approval state, and pull-request workflow.
              </p>
              <div className="showcase-tech-list">
                <span>LangGraph</span>
                <span>FastAPI</span>
                <span>Pydantic</span>
                <span>Async tools</span>
              </div>
            </article>
            <article>
              <div className="showcase-architecture-top">
                <span>03</span>
                <code>data + controls</code>
              </div>
              <h3>Durable audit trail</h3>
              <p>
                SQLite stores runs, findings, approvals, prepared patches, and
                pull-request metadata. Write credentials never reach the
                browser.
              </p>
              <div className="showcase-tech-list">
                <span>SQLite</span>
                <span>GitHub API</span>
                <span>OTLP/HTTP</span>
                <span>CORS boundary</span>
              </div>
            </article>
          </div>
        </section>

        <section className="showcase-final-cta">
          <img src="/logos/docshound.png" alt="" />
          <span className="showcase-section-number">
            FROM SIGNAL TO SOURCE OF TRUTH
          </span>
          <h2>Let the code tell you what the docs are missing.</h2>
          <p>Paste a public GitHub repository. DocsHound will show its work.</p>
          <Link className="showcase-primary-action" to="/">
            Run DocsHound <span aria-hidden="true">→</span>
          </Link>
        </section>
      </main>

      <footer className="showcase-footer">
        <span>
          Docs<span>Hound</span>
        </span>
        <p>Repository activity → reviewed documentation</p>
        <a href="#top">Back to top ↑</a>
      </footer>
    </div>
  );
}
