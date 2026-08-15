# DocsHound OpenCode stage demo

This folder contains a repeatable, live-data demo of DocsHound finding two real
gaps in OpenCode's CLI reference and publishing the reviewed change to a fork.
The preflight is read-only: it does not sync the fork, create branches, or open
pull requests.

## One-command start

From the DocsHound repository root:

```bash
./demo/run.sh opencode
```

Stop any ordinary `./run.sh` process first; the demo launch deliberately fails
instead of silently switching ports when `5173` or `8000` is already occupied.

That command starts a local Phoenix trace viewer, runs every preflight check,
enables the pinned OpenCode scenario, and launches the backend and frontend.

- DocsHound: <http://127.0.0.1:5173>
- OpenInference traces: <http://127.0.0.1:6006>

Stop DocsHound with `Ctrl+C`. Phoenix stays available between rehearsals so
the trace history remains visible. Stop it separately with:

```bash
./demo/phoenix.sh stop
```

## Credentials

Put these in the root `.env` or `backend/.env` before running the demo:

```text
GITHUB_TOKEN=github_pat_...
MERGE_GATEWAY_API_KEY=...
```

Use one GitHub token that can read the public OpenCode repository and can write
to `MatthewFeroz/opencode`. The fork needs Contents and Pull requests read/write
access. The preflight validates the authenticated account, the fork relationship,
push permission, live model access, and the exact source files without printing
either secret.

## Stage flow

1. Run `./demo/run.sh opencode` before presenting. Do not proceed if preflight
   reports a failure.
2. Paste `anomalyco/opencode` into the main Repository field.
3. Connect the same GitHub token checked by preflight.
4. In Official documentation, use **Change source** and select
   `MatthewFeroz/opencode`. Keep the detected root
   `packages/web/src/content/docs`.
5. Start the run. The trace should show exactly these live sources:
   - `anomalyco/opencode#42484` — document non-interactive `mcp add`
   - `anomalyco/opencode#41537` — document mini/replay CLI flags
   - `anomalyco/opencode#31054` — merged implementation for non-interactive
     `mcp add`
6. Review a finding, approve it, and preview the update to
   `packages/web/src/content/docs/cli.mdx`.
7. Create the pull request in `MatthewFeroz/opencode`.

Open Phoenix during the run and choose the `docshound-opencode-demo` project to
show the agent, tool, chain, and model spans. The repository source references
are recorded on the analysis spans without copying issue or document bodies into
DocsHound's custom span attributes.

## Rehearsal commands

Run the checks without launching the product:

```bash
./demo/phoenix.sh start
./demo/preflight.sh opencode
```

Run the entire agent pipeline through a real patch preview without creating a
branch or pull request on GitHub:

```bash
./demo/rehearse.sh opencode
```

This is the strongest safe check to run before stage time. It fetches the exact
live issues and merged PR, requires two findings that cover every pinned source,
searches the fork's full documentation corpus, drafts both changes, and proves
that each patch updates the existing `packages/web/src/content/docs/cli.mdx`.
It uses a temporary local database and deletes it afterward.

Inspect the local trace service:

```bash
./demo/phoenix.sh status
./demo/phoenix.sh logs
```

The preflight intentionally warns, but does not mutate anything, when the fork
is behind upstream. To bring the fork's `dev` branch current before rehearsal,
make that remote change explicitly:

```bash
gh repo sync MatthewFeroz/opencode --source anomalyco/opencode --branch dev
```

## How it works

- [`scenarios/opencode.json`](scenarios/opencode.json) is the stage manifest. It
  pins two issues and one merged PR, their exact titles and states, the source
  and publish repositories, the docs target, implementation markers, and the
  Merge Gateway model.
- [`preflight.py`](preflight.py) verifies every volatile dependency against
  GitHub and Merge Gateway. It also checks that the CLI implementation still
  contains the behavior while the target docs still omit it. If OpenCode closes
  an issue, changes a title, fills the gap, or the token loses publish access,
  the demo stops before you go on stage.
- [`rehearse.py`](rehearse.py) exercises the complete read-only workflow through
  patch generation. It deliberately stops before the GitHub branch/commit/PR
  calls, making it safe to run repeatedly.
- Setting `DOCSHOUND_DEMO_SCENARIO=opencode` makes repository research call the
  normal GitHub API endpoints for only those pinned sources. No issue bodies or
  model output are stored as fixtures. A source-coverage guardrail links issue
  `#42484` to its earlier implementation PR and prevents a model response from
  silently dropping a pinned issue.
- [`compose.yaml`](compose.yaml) runs the pinned Phoenix image with persistent
  local storage. [`run.sh`](run.sh) sends OTLP/HTTP traces to it and groups them
  under `docshound-opencode-demo`.
- [`research/opencode-sources.md`](research/opencode-sources.md) records why
  these sources were selected and the code/documentation evidence behind them.

Outside `DOCSHOUND_DEMO_SCENARIO`, DocsHound keeps its normal behavior and
researches recent repository activity instead of using the demo manifest.
