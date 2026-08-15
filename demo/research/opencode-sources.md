# OpenCode demo source research

Research date: 2026-08-15

## Recommendation

Use a single, tightly scoped **CLI documentation catch-up** scenario:

```yaml
source_repo: anomalyco/opencode
publish_repo: MatthewFeroz/opencode
source_ref: dev
publish_base: dev
issue_numbers:
  - 42484
  - 41537
pull_request_numbers:
  - 31054
expected_documentation_paths:
  - packages/web/src/content/docs/cli.mdx
```

This is a strong stage scenario because all three pinned sources describe already shipped, user-facing CLI behavior whose reference documentation is still visibly incomplete. The resulting change should stay in one English documentation file, which makes the agent's reasoning and the final diff easy to explain on stage.

The story is straightforward: OpenCode added non-interactive MCP registration and a minimal TUI, but the CLI reference did not catch up. DocsHound connects the open documentation reports to the merged implementation, verifies the current command behavior in code, and proposes the missing CLI entries.

## Pinned sources

### 1. Open issue #42484: document non-interactive MCP registration

[Issue #42484](https://github.com/anomalyco/opencode/issues/42484) explicitly asks for documentation of a command such as:

```bash
opencode mcp add github \
  --url https://api.githubcopilot.com/mcp \
  --header "Authorization=Bearer {env:GITHUB_TOKEN}"
```

The request is grounded in shipped behavior. [Merged PR #31054](https://github.com/anomalyco/opencode/pull/31054) added non-interactive local and remote MCP registration, repeatable `--env` and `--header` options, and the same GitHub example. On the audited `dev` commit, the command still defines `--url`, `--env`, and `--header`, validates local-versus-remote combinations, and writes the resulting MCP configuration ([implementation, lines 429–495](https://github.com/anomalyco/opencode/blob/4643e65ad6334de3e4e68dedc201d5fbb828c9fe/packages/opencode/src/cli/cmd/mcp.ts#L429-L495)).

The current English CLI page only presents bare `opencode mcp add` and says the command starts an interactive guide; it has no non-interactive syntax, options, or examples ([current docs, lines 232–243](https://github.com/anomalyco/opencode/blob/4643e65ad6334de3e4e68dedc201d5fbb828c9fe/packages/web/src/content/docs/cli.mdx#L232-L243)).

Expected documentation change:

- Keep the existing interactive command.
- Add remote syntax with `--url` and repeatable `--header`.
- Add local syntax using a command after `--` and repeatable `--env`.
- Explain that `--env` is local-only and `--header` is remote-only.
- Include the GitHub MCP example from the merged PR without embedding a real token.

Target: [`packages/web/src/content/docs/cli.mdx`](https://github.com/anomalyco/opencode/blob/4643e65ad6334de3e4e68dedc201d5fbb828c9fe/packages/web/src/content/docs/cli.mdx)

### 2. Open issue #41537: document minimal-TUI flags

[Issue #41537](https://github.com/anomalyco/opencode/issues/41537) reports that `--mini`, `--no-replay`, and `--replay-limit` are exposed by `opencode tui` and `opencode attach` but missing from the CLI reference.

The current implementation confirms all three options for the default TUI ([TUI options, lines 119–139](https://github.com/anomalyco/opencode/blob/4643e65ad6334de3e4e68dedc201d5fbb828c9fe/packages/opencode/src/cli/cmd/tui.ts#L119-L139)) and for `attach` ([attach options, lines 41–61](https://github.com/anomalyco/opencode/blob/4643e65ad6334de3e4e68dedc201d5fbb828c9fe/packages/opencode/src/cli/cmd/attach.ts#L41-L61)). The implementation also supplies a useful constraint that should be documented: `--no-replay` and `--replay-limit` require `--mini` ([TUI validation, lines 178–185](https://github.com/anomalyco/opencode/blob/4643e65ad6334de3e4e68dedc201d5fbb828c9fe/packages/opencode/src/cli/cmd/tui.ts#L178-L185); [attach validation, lines 97–104](https://github.com/anomalyco/opencode/blob/4643e65ad6334de3e4e68dedc201d5fbb828c9fe/packages/opencode/src/cli/cmd/attach.ts#L97-L104)).

The audited CLI page omits these options from both the TUI flag table ([lines 22–45](https://github.com/anomalyco/opencode/blob/4643e65ad6334de3e4e68dedc201d5fbb828c9fe/packages/web/src/content/docs/cli.mdx#L22-L45)) and the attach flag table ([lines 99–127](https://github.com/anomalyco/opencode/blob/4643e65ad6334de3e4e68dedc201d5fbb828c9fe/packages/web/src/content/docs/cli.mdx#L99-L127)).

Expected documentation change:

- Add `--mini`, `--no-replay`, and `--replay-limit` to both relevant flag tables.
- Preserve the descriptions used by the CLI implementation.
- State that the replay controls require `--mini`.
- For `opencode tui`, state that server/network flags cannot be combined with `--mini`, matching the current validation ([lines 152–185](https://github.com/anomalyco/opencode/blob/4643e65ad6334de3e4e68dedc201d5fbb828c9fe/packages/opencode/src/cli/cmd/tui.ts#L152-L185)).

Target: [`packages/web/src/content/docs/cli.mdx`](https://github.com/anomalyco/opencode/blob/4643e65ad6334de3e4e68dedc201d5fbb828c9fe/packages/web/src/content/docs/cli.mdx)

### 3. Merged PR #31054: implementation evidence

[PR #31054](https://github.com/anomalyco/opencode/pull/31054) is the implementation anchor for issue #42484. It merged on 2026-06-06 and includes the intended local and remote examples plus tests. Pinning the merged PR gives DocsHound both the user request and authoritative implementation history rather than asking it to infer syntax from an issue alone.

## Why this should produce a credible PR

- It is documentation-only and does not require deciding new product behavior.
- The sources agree with current code at the pinned upstream commit.
- Both changes belong in the same existing CLI reference page.
- The commands, option names, validation rules, and example are concrete enough to review during a live demo.
- The topic is operationally harmless: it does not involve a vulnerability, incident, billing dispute, or contentious roadmap request.

Suggested PR title:

```text
docs: complete CLI reference for MCP add and mini TUI
```

Suggested acceptance check after DocsHound drafts the change:

```bash
rg -n -- '--mini|--no-replay|--replay-limit|--url|--env|--header' \
  packages/web/src/content/docs/cli.mdx
```

## Repository and fork preflight

The upstream repository is public, active, uses `dev` as its default branch, and has Issues enabled ([GitHub repository API](https://api.github.com/repos/anomalyco/opencode)).

The intended destination exists: [`MatthewFeroz/opencode`](https://github.com/MatthewFeroz/opencode) is a public fork of `anomalyco/opencode`, uses `dev` as its default branch, and has Issues disabled ([GitHub repository API](https://api.github.com/repos/MatthewFeroz/opencode)). Issues being disabled on the fork is not a problem as long as DocsHound reads activity from `anomalyco/opencode` and publishes the documentation branch to `MatthewFeroz/opencode`.

The authenticated GitHub account used for this read-only audit reported push/admin access to the fork. Both the MCP implementation and the documentation omissions are also present at the fork's audited `dev` commit `d4704347465c1ee63d0c213ed00e648e7f0231c5`, so the proposed demo can produce a valid fork-local PR even before syncing.

However, at the time of the audit, upstream `dev` was at `4643e65ad6334de3e4e68dedc201d5fbb828c9fe` while the fork's `dev` was at `d4704347465c1ee63d0c213ed00e648e7f0231c5`. A SHA-to-SHA comparison reported the upstream head 41 commits ahead of the fork ([GitHub compare API](https://api.github.com/repos/anomalyco/opencode/compare/d4704347465c1ee63d0c213ed00e648e7f0231c5...4643e65ad6334de3e4e68dedc201d5fbb828c9fe)). The demo preflight should warn on drift and recommend syncing the fork before rehearsal; it should not silently mutate the fork.

## Determinism and caveats

1. Fetch the two issues and merged PR **directly by number**. Do not rely on the repository's newest-issues or newest-PR window. A pinned item remains addressable if it later closes, though the preflight should surface the state change.
2. Pin the upstream commit used for source verification in the scenario manifest or generated trace. The live repository can move quickly, and a later commit may close the documentation gap.
3. Issue #42484 links to the Chinese CLI page, while the same omission is independently visible in the current English source. For a clear English-language stage demo, target the canonical English `packages/web/src/content/docs/cli.mdx` and mention this inference in the agent trace. Do not have the model invent a Chinese translation.
4. A fork PR is not proof that upstream maintainers will merge the wording. Present it as a review-ready proposal, not an upstream acceptance guarantee.
5. The preflight must ensure the GitHub token can read `anomalyco/opencode` and push a branch to `MatthewFeroz/opencode`; the fork's disabled Issues setting should never be treated as a source-data failure.

## Optional fallback source

If either primary issue is resolved before the demo and you prefer to show an open gap, use [issue #41925](https://github.com/anomalyco/opencode/issues/41925). It asks the docs to clarify whether `tool/` or `tools/` is canonical. The current docs name only plural directories ([`custom-tools.mdx`, lines 16–21](https://github.com/anomalyco/opencode/blob/4643e65ad6334de3e4e68dedc201d5fbb828c9fe/packages/web/src/content/docs/custom-tools.mdx#L16-L21)), while the loader accepts both via `{tool,tools}` ([registry implementation, lines 181–186](https://github.com/anomalyco/opencode/blob/4643e65ad6334de3e4e68dedc201d5fbb828c9fe/packages/opencode/src/tool/registry.ts#L181-L186)). This is also a safe docs-only change, but it produces a second target file and is less narratively cohesive than the primary CLI scenario.
