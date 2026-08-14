# OpenWiki search and a better retrieval design for DocsHound

Research date: 2026-08-14
OpenWiki source reviewed at commit [`355f4f6`](https://github.com/langchain-ai/openwiki/tree/355f4f68e71bd024631cdcff7aa871c3e72435da). Its pinned Deep Agents dependency is `1.12.0`; framework details below use the corresponding [`bed2d34`](https://github.com/langchain-ai/deepagentsjs/tree/bed2d344bc815b5f550b35c6f1972f7a25fea603) source. This report uses only those repositories and the local DocsHound source.

## Executive conclusion

OpenWiki's main code-search runtime is **agent-driven filesystem discovery, not a conventional vector, BM25, or precomputed retrieval index**. A Deep Agent is rooted at the target repository and decides when to call `ls`, `glob`, literal `grep`, paged `read_file`, and sometimes shell commands. OpenWiki makes that free-form exploration more reliable with a detailed discovery rubric, a planning artifact, an independent skeleton critic, and source-question/wiki-answer verification loops.

The filesystem is therefore an execution surface, not a hidden semantic search database. OpenWiki does persist the generated Markdown wiki, a SQLite conversation checkpointer, and summarized conversation-history files, but it does not build a code embedding index or give each search agent a separate durable repository copy. Init-only subagents receive the same backend and can inspect the same repository; their final response is returned to the parent.

For DocsHound, copying OpenWiki's filesystem agent would add cost and attack surface without addressing the immediate retrieval weakness. The better transfer is its **plan → targeted retrieval → independent coverage test → repair/retrieve again** pattern. Implement that as a bounded LangGraph loop backed by GitHub APIs and an ephemeral, in-memory section index. No clone, shell, agent-owned filesystem, or persistent background worker is required.

## How OpenWiki searches, end to end

### 1. Runtime and available search operations

For a repository run, OpenWiki creates an `OpenWikiLocalShellBackend` rooted at the repository, with virtual paths, a 120-second shell timeout, and 100,000-byte command-output ceiling. It wraps that backend with read-only virtual mounts for skills and conversation-history offload, then gives the Deep Agent filesystem tools, summarization, and selected subagents. Specialized critic/QA subagents are registered only for repository `init`; update runs do not register them. [OpenWiki agent construction](https://github.com/langchain-ai/openwiki/blob/355f4f68e71bd024631cdcff7aa871c3e72435da/src/agent/index.ts#L323-L445) [virtual mounts](https://github.com/langchain-ai/openwiki/blob/355f4f68e71bd024631cdcff7aa871c3e72435da/src/agent/index.ts#L700-L779)

Deep Agents supplies these relevant primitives:

- `ls` is non-recursive directory discovery.
- `glob` finds paths; OpenWiki rejects an unbounded root `**/*` and tells the model to narrow by directory and extension.
- `grep` is literal fixed-string search, using `rg -F` when available and a recursive substring fallback otherwise; it is not semantic search and not regex through the built-in tool.
- `read_file` is line-paged and defaults to 100 lines at a time.
- `ls`, `glob`, and `grep` truncate at an estimated 20,000 tokens and ask the model to narrow the query.

These behaviors are in the [Deep Agents filesystem tool definitions](https://github.com/langchain-ai/deepagentsjs/blob/bed2d344bc815b5f550b35c6f1972f7a25fea603/libs/deepagents/src/middleware/fs.ts#L515-L572), [tool implementations](https://github.com/langchain-ai/deepagentsjs/blob/bed2d344bc815b5f550b35c6f1972f7a25fea603/libs/deepagents/src/middleware/fs.ts#L612-L819), [glob/grep implementations](https://github.com/langchain-ai/deepagentsjs/blob/bed2d344bc815b5f550b35c6f1972f7a25fea603/libs/deepagents/src/middleware/fs.ts#L965-L1117), [literal ripgrep backend](https://github.com/langchain-ai/deepagentsjs/blob/bed2d344bc815b5f550b35c6f1972f7a25fea603/libs/deepagents/src/backends/filesystem.ts#L562-L689), and [result truncation](https://github.com/langchain-ai/deepagentsjs/blob/bed2d344bc815b5f550b35c6f1972f7a25fea603/libs/deepagents/src/backends/utils.ts#L463-L488).

OpenWiki adds access controls around these generic tools. `.openwikiignore` paths are removed from discovery and denied on direct reads; broad root globbing and `.git` globbing are rejected; init/update writes are confined to `openwiki/`. When ignore rules are active, arbitrary shell commands are disabled because they could bypass path filtering. [OpenWiki guarded backend](https://github.com/langchain-ai/openwiki/blob/355f4f68e71bd024631cdcff7aa871c3e72435da/src/agent/docs-only-backend.ts#L52-L139) [discovery filtering](https://github.com/langchain-ai/openwiki/blob/355f4f68e71bd024631cdcff7aa871c3e72435da/src/agent/docs-only-backend.ts#L236-L327)

### 2. Candidate generation and ordering are prompt-driven

On initialization, the model is told to inventory manifests/workspaces, applications and services, runtime entrypoints, public surfaces, domains, schemas/state ownership, operational configuration, existing docs, and representative tests. It must then rank areas by runtime importance, dependency centrality, recent change activity, public surface, and test ownership; group related files by imports, symbols, calls, shared data, tests, and history; and write a skeleton before prose. [OpenWiki init workflow](https://github.com/langchain-ai/openwiki/blob/355f4f68e71bd024631cdcff7aa871c3e72435da/src/agent/prompts/code.ts#L112-L151)

Before documenting a planned area, the prompt requires evidence from the runtime entrypoint, primary implementation, public types/configuration, persistence or state code, an upstream caller, a downstream dependency, representative failure-path tests, and relevant generated/operational artifacts. That rubric drives iterative follow-the-symbol exploration. [OpenWiki evidence gate](https://github.com/langchain-ai/openwiki/blob/355f4f68e71bd024631cdcff7aa871c3e72435da/src/agent/prompts/code.ts#L165-L182)

This is important: the five ranking signals are instructions to the model. There is no deterministic scorer in OpenWiki that computes dependency centrality, BM25, embeddings, or a ranked candidate list. Relevance comes from the model repeatedly narrowing searches and following evidence.

### 3. Iterative retrieval and independent checks

OpenWiki adds two verification layers after initial exploration:

1. A `skeleton_critic` independently maps the repository before reading the proposed skeleton, follows representative paths across boundaries, and reports all material coverage gaps. The main agent addresses those requests and invokes the critic exactly once more. [Skeleton critic](https://github.com/langchain-ai/openwiki/blob/355f4f68e71bd024631cdcff7aa871c3e72435da/src/agent/skeleton_critic.ts#L4-L68)
2. A `wiki_question_finder` searches source and tests, not the wiki, to generate at most ten high-risk engineering questions (target eight for a large repository). A separate `wiki_answer_verifier` searches only the wiki and grades batches of one to three questions as PASS, PARTIAL, or FAIL. Missing answers cause documentation repair and another verification wave. [Question generation and answer verification](https://github.com/langchain-ai/openwiki/blob/355f4f68e71bd024631cdcff7aa871c3e72435da/src/agent/wiki_qa_subagents.ts#L4-L112) [parent batching/retry instructions](https://github.com/langchain-ai/openwiki/blob/355f4f68e71bd024631cdcff7aa871c3e72435da/src/agent/prompts/code.ts#L143-L149)

This loop is the strongest transferable idea. It tests retrieval/coverage with questions derived independently from source evidence instead of trusting the first search result or a single model confidence score.

### 4. Update and chat search are narrower

Update runs start from the existing wiki and last recorded Git commit, use the diff to build a docs-impact plan, rank affected areas with the same signals, follow one-hop dependencies, and avoid a full inventory unless structure changed or an obvious gap appears. The update prompt explicitly says to work in the top-level agent and avoid subagents unless the user requested them. [Update mapping discipline](https://github.com/langchain-ai/openwiki/blob/355f4f68e71bd024631cdcff7aa871c3e72435da/src/agent/prompts/code.ts#L228-L243) [Git-scoped update](https://github.com/langchain-ai/openwiki/blob/355f4f68e71bd024631cdcff7aa871c3e72435da/src/agent/prompts/code.ts#L381-L400)

Chat runs search the generated wiki first, using its quickstart/index pages and targeted grep/glob, and fall back to source only when the wiki cannot answer. [Wiki-first chat rules](https://github.com/langchain-ai/openwiki/blob/355f4f68e71bd024631cdcff7aa871c3e72435da/src/agent/prompts/code.ts#L23-L27)

### 5. Indexing and context assembly

OpenWiki's durable “index” is the generated wiki itself: Markdown pages, directory `index.md` files, links between concepts, and OKF front matter with retrieval-oriented descriptions plus optional source paths, symbols, tests, invariants, and validation commands. [OKF retrieval metadata](https://github.com/langchain-ai/openwiki/blob/355f4f68e71bd024631cdcff7aa871c3e72435da/src/agent/prompts/code.ts#L304-L344) This makes future lexical/navigation search better, but it is not a vector or inverted index over the original codebase.

Context is assembled implicitly through the agent conversation: selected directory listings, grep matches, paged file excerpts, subagent final answers, and eventually a model-generated conversation summary. Deep Agents gives both the parent and declarative subagents filesystem and summarization middleware; task execution resets a subagent's messages to the delegated task and forwards its final answer/state update back to the parent. [Deep Agent middleware composition](https://github.com/langchain-ai/deepagentsjs/blob/bed2d344bc815b5f550b35c6f1972f7a25fea603/libs/deepagents/src/agent.ts#L255-L390) [subagent task invocation](https://github.com/langchain-ai/deepagentsjs/blob/bed2d344bc815b5f550b35c6f1972f7a25fea603/libs/deepagents/src/middleware/subagents.ts#L542-L605)

There is no explicit “top K chunks, rerank, pack to N tokens” stage. That flexibility helps deep repository understanding, but makes latency, token use, and recall depend heavily on model behavior.

## How DocsHound differs today

DocsHound's workflow is deterministic in ordering—research, cluster, search docs, draft, store—even though an LLM router chooses an action subject to a guardrail. [DocsHound graph](../../backend/app/langgraph_agent.py#L46-L159) [nodes and edges](../../backend/app/langgraph_agent.py#L181-L344)

Its documentation search is a two-stage lexical funnel:

1. Fetch the GitHub tree and keep `.md`/`.mdx` files under known documentation path markers plus READMEs; prefer canonical/English locale variants.
2. For each finding, score **paths only** from simple token overlap, select 10 paths per finding when authenticated (5 public), deduplicate in finding order, and download at most 60 unique documents globally (24 public).
3. Re-rank only those downloaded documents using token overlap over path, title, and the first 8,000 content characters. Keep five pages per finding authenticated (three public).
4. Send the first 5,000 characters of each kept page to one model call that assesses every finding.

The implementation is in [docs.py candidate loading](../../backend/app/tools/docs.py#L214-L284), [path and document scoring](../../backend/app/tools/docs.py#L352-L405), and [coverage assessment](../../backend/app/tools/docs.py#L477-L537).

The most consequential limitations are:

- **Content cannot rescue a bad path pre-rank.** A highly relevant page with an opaque path is never downloaded, so the later content scorer cannot see it.
- **The 60-document ceiling is global and order-sensitive.** Unique paths are appended finding by finding and sliced only after that; earlier findings can consume the fetch budget.
- **The unit is a whole page prefix, not a section.** Relevant material below 5,000 characters is invisible to the coverage model, while repeated headers/navigation consume context.
- **Search is exact-token lexical only.** There is no stemming, synonym expansion, semantic candidate path, exact error/symbol lane, heading weighting, link/nav graph, or diversity control.
- **There is no adaptive second pass.** A low-confidence or incomplete coverage decision cannot request a refined query or a neighboring page.
- **`docs_url` is not searched.** DocsHound fetches only the configured homepage title; it does not crawl or extract page content. [Homepage handling](../../backend/app/tools/docs.py#L557-L590)
- **Repository tree truncation is not handled.** The code consumes the recursive tree response without checking GitHub's `truncated` flag.
- **One assessment prompt can become broad.** With eight findings and five candidate pages each, up to 40 page prefixes are packed into a single coverage decision, including duplicates across findings.

Separate upstream limits also cap breadth: the frontend requests 50 issues, the API permits 100, clustering sends only the first 60 issues and 30 PRs to the model, and at most eight findings survive. [Frontend run request](../../frontend/src/api.ts#L45-L61) [API limit](../../backend/app/api_models.py#L6-L10) [cluster input/output caps](../../backend/app/tools/cluster.py#L95-L166)

## Recommended design: bounded agentic retrieval without a filesystem

Keep the existing LangGraph workflow, but replace the single `search_docs` operation with a bounded subgraph:

```text
build criteria + queries
        ↓
catalog paths at commit SHA
        ↓
fetch and section-index candidates
        ↓
hybrid candidate generation → rerank/diversify → assemble evidence
        ↓                                      ↑
criteria-level coverage verifier ──search requests (max 2 rounds)
        ↓
final coverage + cited sections + recommended page/action
```

### A. Turn each finding into testable coverage criteria

Create a structured retrieval plan per finding, not just one bag of tokens:

- user intent/question;
- exact identifiers, error strings, commands, configuration keys, and feature names;
- symptoms and likely synonyms;
- for shipped changes, touched paths/symbols and user-visible behavior from the PR;
- three to five criteria that documentation must answer to count as `documented`.

Generate two to four search queries from those fields. This borrows OpenWiki's source-question/acceptance-criteria idea while remaining a normal structured model call.

### B. Build an ephemeral section index through GitHub APIs

Pin every run to the default branch commit SHA. Load the tree once. If GitHub reports a truncated recursive tree, traverse subtrees rather than silently accepting partial coverage. Fetch candidate blobs through the Git Data API with bounded concurrency and byte limits; do not clone the repository.

Parse Markdown/MDX into heading-based sections. Each in-memory record should contain:

```text
section_id, blob_sha, path, canonical_locale, title, heading_breadcrumb,
frontmatter, body, outbound_links, code_identifiers, start_line, end_line
```

For the current scale, fetch/index all eligible docs up to a budget such as 500 files or 25 MB of text. Above that, use path/nav-config candidates plus exact GitHub code-search hits to select blobs. The index lives only for the run; a service-owned cache keyed by `repo + commit SHA` can be added later for speed without exposing storage to the model.

### C. Use multiple candidate lanes, then reciprocal-rank fusion

Generate a union of candidates per finding:

- BM25-style lexical search over title, heading, path, front matter, and body;
- exact identifier/error/command matches with high weight;
- optional embedding similarity for paraphrases;
- path/filename similarity;
- PR-touched documentation and pages linked from docs navigation.

Fuse lane ranks with reciprocal-rank fusion rather than trying to normalize unrelated scores. Then rerank the top 20–30 sections against the coverage criteria. Enforce diversity—normally no more than two sections per page before expansion—so five near-duplicate chunks do not crowd out a complementary setup or troubleshooting page.

Embeddings are useful but not required for the first release. BM25 + exact identifiers + query expansion will already be materially stronger than the current set-overlap scorer.

### D. Make verification able to search again

Assess one finding at a time. The verifier must return, for each criterion:

```json
{
  "criterion": "...",
  "status": "covered | partial | missing | conflicting",
  "evidence_section_ids": ["..."],
  "missing_detail": "...",
  "followup_queries": ["..."]
}
```

If any criterion is partial/missing and the verifier offers a materially new query, run at most two refinement rounds. Refinement can perform exact phrase/symbol searches, fetch linked pages, inspect adjacent sections in the same page, or expand to nav siblings. Stop when there are no new high-scoring sections, all criteria pass, or the request/token/API budget is exhausted.

This is the controlled analogue of OpenWiki's critic and QA loops. It is auditable because every extra retrieval is represented in graph state, not hidden in an open-ended agent conversation.

### E. Assemble section-level context under a fixed budget

Pack evidence per finding, not all findings together. Prefer complete relevant sections with breadcrumb, path, line range, and stable source ID. Include adjacent context only when necessary. Deduplicate repeated sections and reserve space for at least one complementary page. A practical starting budget is 8–12 sections and roughly 12,000–20,000 input tokens per finding; the verifier's evidence IDs become the displayed sources and recommended update target.

### F. Keep the model away from storage and shell

If the retrieval step is exposed as tools, expose only narrow service calls such as:

- `search_doc_sections(finding_id, query, filters, k)`
- `fetch_doc_sections(section_ids)`
- `expand_doc_neighbors(section_ids)`

The service validates the repository, commit, allowed extensions, byte budget, and path. The model never receives a shell, host path, clone, write capability, or persistent private workspace. Repository content remains untrusted data in every prompt.

## Safe depth and rollout

The current 60-document limit is compensating for request count and prompt size, not a fundamental search limit. Section indexing decouples corpus depth from model context: hundreds of pages can be searched while only a small evidence set is sent to the model.

Recommended rollout:

1. **First improvement:** section parsing, BM25/exact-match lanes, per-finding assessment, and no model-visible filesystem. Keep the existing GitHub tree/content APIs.
2. **Then add adaptivity:** criteria and a maximum of two follow-up retrieval rounds.
3. **Then add semantic recall:** embeddings only if evals show lexical/query-expansion misses.
4. **Finally cache by commit SHA:** service-managed and replaceable, never agent-owned.

Suggested initial budgets:

| Budget | Starting value |
|---|---:|
| Eligible docs fetched/indexed | 500 files or 25 MB text |
| Candidate sections before rerank | 30 per finding |
| Final evidence | 8–12 sections per finding |
| Refinement rounds | 2 |
| Concurrent GitHub blob requests | 8 |
| Coverage model calls | one per finding, concurrency-limited |

The limits to monitor are GitHub rate consumption, fetched bytes, parse time, reranker latency, unique evidence sections, criteria pass rate, and the fraction of findings that need a second round. Do not use “documents inspected” alone as a quality metric; measure whether known relevant sections were retrieved and whether the verifier's cited evidence truly satisfies each criterion.

## What to borrow from OpenWiki—and what not to

Borrow:

- explicit discovery/coverage criteria before drafting;
- multiple search formulations and following one-hop evidence;
- an independent verifier that cannot simply repeat the first assessment;
- iterative repair/retrieval with a hard budget;
- source IDs, symbols, tests, and relationships as retrieval metadata;
- narrow, paged context rather than full-file dumping.

Do not borrow:

- unrestricted or general-purpose shell execution;
- model-directed repository-wide exploration for every finding;
- agent-owned persistent files as the retrieval substrate;
- a single long conversation as the only search state;
- prompt-only ranking signals without deterministic observability.

The resulting DocsHound search would be deeper than its current five-page assessment, more predictable than OpenWiki's free-form filesystem exploration, and compatible with the existing review-first product flow.
