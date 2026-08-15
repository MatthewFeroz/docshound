#!/usr/bin/env python3
"""Run the complete demo pipeline through patch preview without writing to GitHub."""

from __future__ import annotations

import argparse
import asyncio
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", default="opencode")
    return parser.parse_args()


async def rehearse(scenario_name: str) -> None:
    # Load credentials before importing app modules because Settings is cached.
    load_dotenv(ROOT / ".env", override=False)
    load_dotenv(ROOT / "backend" / ".env", override=False)
    os.environ["DOCSHOUND_DEMO_SCENARIO"] = scenario_name

    from app.approved_documents import ApprovedDocument
    from app.config import get_settings
    from app.demo_scenarios import load_demo_scenario
    from app.documentation_prs import prepare_documentation_change
    from app.state import DocumentationSource
    from app.tools.cluster import cluster_issues, draft_review_documents
    from app.tools.docs import search_official_docs
    from app.tools.github import research_pull_requests, research_repo

    scenario = load_demo_scenario(scenario_name)
    settings = get_settings()
    if not settings.github_token:
        raise RuntimeError("GITHUB_TOKEN was not loaded for the rehearsal.")
    if not settings.merge_gateway_api_key and not settings.openai_api_key:
        raise RuntimeError("A model credential was not loaded for the rehearsal.")
    expected_issue_refs = {
        f"{scenario.source_repository}#{reference.number}"
        for reference in scenario.issues
    }
    expected_pr_refs = {
        f"{scenario.source_repository}#{reference.number}"
        for reference in scenario.pull_requests
    }

    print(f"DocsHound full rehearsal · {scenario.title}")
    issues, pull_requests = await asyncio.gather(
        research_repo(scenario.source_repository, 50),
        research_pull_requests(scenario.source_repository, 50),
    )
    actual_issue_refs = {f"{issue.source_repo}#{issue.number}" for issue in issues}
    actual_pr_refs = {
        f"{pull_request.source_repo}#{pull_request.number}"
        for pull_request in pull_requests
    }
    if actual_issue_refs != expected_issue_refs or actual_pr_refs != expected_pr_refs:
        raise RuntimeError(
            "GitHub research did not return exactly the scenario's pinned sources."
        )
    print(
        f"[PASS] research  {len(issues)} issues and "
        f"{len(pull_requests)} merged pull request"
    )

    findings = await cluster_issues(
        issues,
        pull_requests,
        product_repo=scenario.source_repository,
    )
    covered_issue_refs = {
        reference for finding in findings for reference in finding.issue_refs
    }
    covered_pr_refs = {
        reference for finding in findings for reference in finding.pr_refs
    }
    if not expected_issue_refs.issubset(covered_issue_refs):
        raise RuntimeError("The analysis omitted at least one pinned issue.")
    if not expected_pr_refs.issubset(covered_pr_refs):
        raise RuntimeError("The analysis omitted the pinned implementation PR.")
    if len(findings) != len(scenario.issues):
        raise RuntimeError(
            f"Expected {len(scenario.issues)} stage findings, got {len(findings)}."
        )
    print(f"[PASS] analysis  {len(findings)} findings cover every pinned source")

    docs_source = DocumentationSource(
        repo=scenario.publish_repository,
        root=scenario.documentation_root,
        confidence=1.0,
        discovered_by="demo_manifest",
    )
    findings, sources, inspected_count = await search_official_docs(
        scenario.source_repository,
        None,
        findings,
        documentation_source=docs_source,
    )
    for finding in findings:
        coverage = finding.documentation_coverage
        if (
            not coverage
            or coverage.recommended_action != "update_page"
            or coverage.recommended_path != scenario.target_path
        ):
            raise RuntimeError(
                f"{finding.name!r} did not resolve to an update of "
                f"{scenario.target_path}."
            )
    print(
        f"[PASS] docs      inspected {inspected_count} pages; every finding "
        f"updates {scenario.target_path}"
    )

    findings = await draft_review_documents(findings, issues, pull_requests)
    if any(not (finding.draft_markdown or "").strip() for finding in findings):
        raise RuntimeError("At least one finding did not produce a review draft.")
    print(f"[PASS] drafting  {len(findings)} reviewable documentation drafts")

    now = datetime.now(timezone.utc).isoformat()
    for index, finding in enumerate(findings):
        document = ApprovedDocument(
            slug=f"demo-rehearsal-{scenario_name}-{index + 1}",
            run_id=f"demo-rehearsal-{scenario_name}",
            gap_index=index,
            repo=scenario.source_repository,
            title=finding.draft_title or finding.name,
            summary=finding.draft_summary or finding.summary,
            markdown=finding.draft_markdown or "",
            source_issues=[
                {
                    "number": issue.number,
                    "title": issue.title,
                    "url": str(issue.url),
                }
                for issue in issues
                if f"{issue.source_repo}#{issue.number}" in finding.issue_refs
            ],
            approved_at=now,
            updated_at=now,
        )
        change = await prepare_documentation_change(
            document,
            target_repo=scenario.publish_repository,
            requested_path=scenario.target_path,
            edit_action="update_page",
        )
        if (
            change.status != "preview_ready"
            or change.file_path != scenario.target_path
            or not change.existing_sha
            or not change.patch.strip()
        ):
            raise RuntimeError(
                f"Patch preview {index + 1} was not ready for the expected file."
            )
    print(
        f"[PASS] preview   {len(findings)} patches apply to "
        f"{scenario.publish_repository} without GitHub writes"
    )
    print(
        f"\nReady: live research → analysis → {len(sources)} docs sources → "
        "draft → fork patch preview all passed."
    )


def main() -> int:
    args = parse_args()
    with tempfile.TemporaryDirectory(prefix="docshound-rehearsal-") as directory:
        os.environ["DOCSHOUND_DB_PATH"] = str(Path(directory) / "docshound.db")
        try:
            asyncio.run(rehearse(args.scenario))
        except Exception as exc:
            print(f"\n[FAIL] {exc}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
