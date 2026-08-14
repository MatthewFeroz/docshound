# DocsHound live-run depth: Pi, T3 Code, and OpenCode

Run date: 2026-08-14

These are live DocsHound runs against the current default branches of:

- [`earendil-works/pi`](https://github.com/earendil-works/pi)
- [`pingdotgg/t3code`](https://github.com/pingdotgg/t3code)
- [`anomalyco/opencode`](https://github.com/anomalyco/opencode)

Each run used the current frontend-equivalent configuration: 50 GitHub issues,
up to 30 merged pull requests, authenticated repository documentation search,
no explicit `docs_url`, and the configured Merge Gateway model route. The three
runs were started together, so elapsed times are useful directional numbers but
not an isolated performance benchmark.

## Headline comparison

| Metric | Pi | T3 Code | OpenCode |
|---|---:|---:|---:|
| Repository blobs | 1,373 | 15,966 | 6,513 |
| Issues inspected | 50 | 50 | 50 |
| Merged PRs inspected | 30 | 30 | 30 |
| Findings produced | 6 | 6 | 7 |
| Official canonical documentation pages | **30** | **30** | **36** |
| Official documentation pages fetched | **17** | **14** | **7** |
| Official corpus fetched | **56.7%** | **46.7%** | **19.4%** |
| Other READMEs/docs fetched | 16 | 3 | 12 |
| Total document bodies fetched | 33 | 17 | 19 |
| Page-assessment slots used | 30 | 30 | 35 |
| Assessment slots filled by official docs | 18 | 29 | 21 |
| Unique official pages assessed by the coverage model | 9 | 10 | 7 |
| Unique pages retained as relevant evidence | 7 | 11 | 7 |
| Coverage results | 6 missing | 6 missing | 7 missing |
| Run status | Completed | Completed | Completed |
| Errors | 0 | 0 | 0 |
| Elapsed time | 48.10s | 44.87s | 32.50s |

“Official canonical documentation pages” uses the actual published source
directory for each project: `packages/coding-agent/docs` for Pi, `docs/` for T3
Code, and the English pages directly under `packages/web/src/content/docs` for
OpenCode. It excludes translated copies, package READMEs, examples, and other
documentation trees that are not part of the primary product documentation.

“Page-assessment slots” counts every page supplied for every finding. The same
page can be assessed for several findings. “Unique pages assessed” removes that
reuse.

## What the depth means

### Pi: broadest corpus coverage

Pi is the shortest and cleanest demonstration. It has 30 official published
pages. DocsHound fetched 17, or 56.7% of that corpus, plus 16 secondary package
READMEs and technical pages. Six findings each received five candidate pages,
but only 18 of the 30 assessment slots came from official docs, representing
nine distinct official pages.

Representative finding: **Broad Substring Model Matching Resolving to
Unconfigured Providers**.

The coverage model assessed:

1. `packages/coding-agent/docs/providers.md`
2. `packages/coding-agent/README.md`
3. `packages/coding-agent/docs/models.md`
4. `packages/coding-agent/docs/containerization.md`
5. `packages/coding-agent/examples/extensions/subagent/README.md`

It retained `providers.md` and `models.md` as the relevant evidence.

Demo interpretation: Pi's smaller documentation surface lets the current
path-first search inspect more than half of the official corpus, but almost
half of the download budget still goes to secondary READMEs and examples.

### T3 Code: compact docs inside a very large repository

T3 Code had the largest repository tree but only 30 official Markdown docs.
DocsHound fetched 14, or 46.7% of that corpus, plus three secondary READMEs.
Six findings used 30 assessment slots; 29 slots came from official docs,
representing ten distinct official pages.

Representative finding: **Stale File Preview Cache on External and Agent
Modifications**.

The coverage model assessed and retained:

1. `docs/internals/connection-runtime.md`
2. `docs/internals/server-updates.md`
3. `docs/internals/overview.md`
4. `docs/internals/resource-telemetry.md`
5. `docs/internals/glossary.md`

Demo interpretation: repository size alone does not determine search depth.
The documentation corpus is compact, but the path prefilter still leaves more
than half of the eligible docs unfetched.

### OpenCode: translations are handled, but the candidate funnel is narrow

OpenCode has 36 canonical English pages in its published documentation source.
DocsHound fetched only seven, or 19.4% of that official corpus, plus 12 pages
from other documentation trees and package READMEs. Seven findings used 35
assessment slots; 21 slots came from the same seven official pages. The
repository also exposes hundreds of translated copies, which DocsHound
successfully canonicalizes away before fetching content.

Representative finding: **Inability to paste file and image paths as plain
text in CLI/TUI**.

The coverage model assessed:

1. `packages/web/src/content/docs/cli.mdx`
2. `packages/web/src/content/docs/tui.mdx`
3. `packages/web/src/content/docs/agents.mdx`
4. `packages/web/src/content/docs/models.mdx`
5. `packages/web/src/content/docs/themes.mdx`

It retained `cli.mdx` and `tui.mdx` as the relevant evidence.

Demo interpretation: canonicalization prevents translated duplicates from
dominating the run, but only one quarter of the remaining eligible pool is
downloaded. OpenCode is therefore the clearest demonstration of why candidate
recall matters before the five-page assessment stage.

## Recommended demo talk track

> Every run starts with the same activity depth: 50 issues and 30 merged pull
> requests. The difference appears in documentation retrieval. Pi has 30
> official pages and DocsHound fetches 17. T3 Code also has 30 and fetches 14.
> OpenCode has 36 English pages but fetches only seven. Every finding still gets
> five documents, yet some of those documents are package READMEs or unrelated
> documentation trees. The next improvement is to identify the canonical docs
> source, fetch the whole small corpus, and retrieve relevant sections from it—not
> merely raise the five-page limit.

## What should become deeper

There are two independent depth axes:

1. **Activity depth:** issues and merged pull requests are used to discover
   candidate documentation gaps. Raising this safely requires batching the
   activity and merging/deduplicating findings.
2. **Documentation depth:** existing official pages are searched to decide
   whether each candidate is truly missing. More documentation context reduces
   false gaps; it does not itself discover more issue themes.

For these three repositories, the highest-value retrieval change is to resolve
the canonical docs root and fetch all official pages because each corpus has
only 30–36 pages. Parse those pages into heading-level sections, build an
ephemeral in-memory index, and send only the best 8–12 sections per finding to
the coverage model. Secondary package READMEs can remain a follow-up search
lane instead of consuming the primary retrieval budget.

## Important caveat

All 19 findings were classified as `missing` by the current coverage model.
That means “missing under the evidence retrieved by this run,” not that a human
audit has proved all 19 documentation gaps. The current path-first candidate
funnel and page-prefix context can create false negatives. These runs are best
used to demonstrate retrieval depth and the need for a coverage critic, not as
a benchmark of final documentation accuracy.

## Persisted run IDs

| Repository | Run ID |
|---|---|
| Pi | `5e92bbc4-b428-4123-9241-2009b72fa99a` |
| T3 Code | `65b8c712-c39b-454a-8991-7494fe87931d` |
| OpenCode | `908debf1-e11a-43a0-b05b-9781045aa3c9` |

The runs are stored in DocsHound's normal run database and can be loaded in the
application for finding-level drill-down.
