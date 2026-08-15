#!/usr/bin/env python3
"""Validate a pinned DocsHound demo scenario without exposing credentials."""

from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SCENARIO_DIRECTORY = ROOT / "demo" / "scenarios"
sys.path.insert(0, str(ROOT / "backend"))

from app.tracing_config import (  # noqa: E402
    DEFAULT_LANGSMITH_ENDPOINT,
    resolve_trace_export_config,
)


@dataclass(frozen=True)
class Result:
    status: str
    name: str
    detail: str


class Report:
    def __init__(self) -> None:
        self.results: list[Result] = []

    def pass_(self, name: str, detail: str) -> None:
        self.results.append(Result("PASS", name, detail))

    def warn(self, name: str, detail: str) -> None:
        self.results.append(Result("WARN", name, detail))

    def fail(self, name: str, detail: str) -> None:
        self.results.append(Result("FAIL", name, detail))

    @property
    def failed(self) -> bool:
        return any(result.status == "FAIL" for result in self.results)

    def print(self) -> None:
        width = max((len(result.name) for result in self.results), default=0)
        for result in self.results:
            print(f"[{result.status}] {result.name:<{width}}  {result.detail}")
        passed = sum(result.status == "PASS" for result in self.results)
        warnings = sum(result.status == "WARN" for result in self.results)
        failed = sum(result.status == "FAIL" for result in self.results)
        print(f"\nSummary: {passed} passed, {warnings} warnings, {failed} failed")


class GitHubClient:
    def __init__(self, token: str) -> None:
        self.headers = {
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "User-Agent": "docshound-demo-preflight",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.rate_limit_remaining: int | None = None

    def get(self, path: str, query: dict[str, str] | None = None) -> Any:
        url = f"https://api.github.com{path}"
        if query:
            url = f"{url}?{urllib.parse.urlencode(query)}"
        payload, headers = _request_json(url, headers=self.headers)
        remaining = headers.get("X-RateLimit-Remaining")
        if remaining and remaining.isdigit():
            self.rate_limit_remaining = int(remaining)
        return payload


def _request_json(
    url: str,
    *,
    headers: dict[str, str],
    timeout: float = 20,
) -> tuple[Any, Any]:
    request = urllib.request.Request(
        url,
        headers=headers,
        method="GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8")), response.headers
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            message = json.loads(raw).get("message", raw[:240])
        except json.JSONDecodeError:
            message = raw[:240]
        raise RuntimeError(f"HTTP {exc.code}: {message}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Could not connect to {url}: {exc.reason}") from exc


def _load_environment() -> tuple[dict[str, str], list[Path]]:
    values: dict[str, str] = {}
    loaded: list[Path] = []
    for path in (ROOT / ".env", ROOT / "backend" / ".env"):
        if not path.is_file():
            continue
        loaded.append(path)
        for raw_line in path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            if line.startswith("export "):
                line = line[7:].lstrip()
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip()
            if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
                value = value[1:-1]
            values[key] = value
    values.update({key: value for key, value in os.environ.items() if value})
    return values, loaded


def _load_scenario(name: str) -> dict[str, Any]:
    if not name or any(
        character not in "abcdefghijklmnopqrstuvwxyz0123456789_-" for character in name
    ):
        raise RuntimeError(
            "Scenario names may contain lowercase letters, numbers, _ and -"
        )
    path = SCENARIO_DIRECTORY / f"{name}.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise RuntimeError(f"Scenario not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid scenario JSON at {path}: {exc}") from exc
    required = (
        "title",
        "source_repository",
        "publish_repository",
        "issues",
        "pull_requests",
        "documentation",
    )
    missing = [key for key in required if key not in payload]
    if missing:
        raise RuntimeError(f"Scenario is missing: {', '.join(missing)}")
    if not payload["issues"] and not payload["pull_requests"]:
        raise RuntimeError("Scenario must pin at least one issue or pull request")
    return payload


def _repo_path(repository: str) -> str:
    return urllib.parse.quote(repository, safe="/")


def _contents_path(repository: str, path: str) -> str:
    return (
        f"/repos/{_repo_path(repository)}/contents/{urllib.parse.quote(path, safe='/')}"
    )


def check_toolchain(report: Report, *, require_free_app_ports: bool) -> None:
    for command in ("git", "bun"):
        executable = shutil.which(command)
        if executable:
            report.pass_(f"tool:{command}", executable)
        else:
            report.fail(f"tool:{command}", f"Install {command} before the demo.")
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg:
        report.pass_("tool:ffmpeg", ffmpeg)
    else:
        report.warn(
            "tool:ffmpeg", "Not required by DocsHound, but unavailable for recording."
        )
    if (ROOT / "frontend" / "node_modules").is_dir():
        report.pass_("frontend dependencies", "frontend/node_modules is installed")
    else:
        report.fail("frontend dependencies", "Run: bun install --cwd frontend")
    if require_free_app_ports:
        for port, service in ((8000, "backend"), (5173, "frontend")):
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
                probe.settimeout(0.5)
                in_use = probe.connect_ex(("127.0.0.1", port)) == 0
            if in_use:
                report.fail(
                    f"port:{port}",
                    f"Already in use. Stop the existing {service} before launch.",
                )
            else:
                report.pass_(f"port:{port}", f"Available for the {service}")


def check_github(
    report: Report,
    scenario: dict[str, Any],
    environment: dict[str, str],
) -> None:
    token = environment.get("GITHUB_TOKEN", "").strip()
    if not token:
        if environment.get("GITHUB_WRITE_TOKEN"):
            report.fail(
                "GitHub token",
                "GITHUB_WRITE_TOKEN is obsolete. Move that value to GITHUB_TOKEN.",
            )
        else:
            report.fail("GitHub token", "Set GITHUB_TOKEN in .env or backend/.env.")
        return
    report.pass_("GitHub token", "Configured (value redacted)")
    github = GitHubClient(token)
    source = scenario["source_repository"]
    publish = scenario["publish_repository"]
    try:
        account = github.get("/user")
        report.pass_("GitHub account", str(account.get("login") or "authenticated"))
        source_payload = github.get(f"/repos/{_repo_path(source)}")
        report.pass_(
            "source repository",
            f"{source_payload['full_name']} · default {source_payload['default_branch']}",
        )
        publish_payload = github.get(f"/repos/{_repo_path(publish)}")
        permissions = publish_payload.get("permissions") or {}
        if permissions.get("push"):
            report.pass_(
                "publish access", f"{publish} allows branch and content writes"
            )
        else:
            report.fail(
                "publish access",
                f"The connected token cannot push to {publish}.",
            )
        parent = ((publish_payload.get("parent") or {}).get("full_name") or "").lower()
        if publish_payload.get("fork") and parent == source.lower():
            report.pass_("fork relationship", f"{publish} is a fork of {source}")
        else:
            report.fail("fork relationship", f"{publish} is not a fork of {source}")

        source_ref = scenario.get("source_ref") or source_payload["default_branch"]
        publish_ref = scenario.get("publish_base") or publish_payload["default_branch"]
        source_head = github.get(
            f"/repos/{_repo_path(source)}/git/ref/heads/{urllib.parse.quote(source_ref, safe='')}"
        )
        publish_head = github.get(
            f"/repos/{_repo_path(publish)}/git/ref/heads/{urllib.parse.quote(publish_ref, safe='')}"
        )
        source_sha = str((source_head.get("object") or {}).get("sha") or "")
        publish_sha = str((publish_head.get("object") or {}).get("sha") or "")
        researched_sha = str(scenario.get("researched_source_commit") or "")
        if researched_sha and source_sha == researched_sha:
            report.pass_(
                "researched revision",
                f"Upstream {source_ref} remains at {source_sha[:10]}",
            )
        elif researched_sha:
            report.warn(
                "researched revision",
                f"Upstream moved from {researched_sha[:10]} to {source_sha[:10]}; "
                "the source-level checks below still decide readiness.",
            )
        pinned_publish_sha = str(scenario.get("publish_base_commit") or "")
        if pinned_publish_sha and publish_sha == pinned_publish_sha:
            report.pass_(
                "fork snapshot",
                f"{publish_ref} intentionally pinned at {publish_sha[:10]}",
            )
        elif pinned_publish_sha:
            report.fail(
                "fork snapshot",
                f"Expected {publish_ref} at {pinned_publish_sha[:10]}, "
                f"but it moved to {publish_sha[:10]}.",
            )
        elif source_sha == publish_sha:
            report.pass_(
                "fork synchronization", f"{publish_ref} matches upstream {source_ref}"
            )
        else:
            report.warn(
                "fork synchronization",
                "The fork differs from upstream and has no publish_base_commit pin.",
            )

        for reference in scenario["issues"]:
            number = int(reference["number"])
            issue = github.get(f"/repos/{_repo_path(source)}/issues/{number}")
            if issue.get("pull_request"):
                report.fail(
                    f"issue #{number}", "Manifest entry resolves to a pull request."
                )
                continue
            if issue.get("title") != reference["title"]:
                report.fail(
                    f"issue #{number}",
                    f"Title changed to: {issue.get('title')}",
                )
                continue
            required_state = str(reference.get("required_state") or "").lower()
            if (
                required_state
                and str(issue.get("state") or "").lower() != required_state
            ):
                report.fail(
                    f"issue #{number}",
                    f"Expected {required_state}, now {issue.get('state')}.",
                )
                continue
            body_length = len((issue.get("body") or "").strip())
            report.pass_(
                f"issue #{number}",
                f"{issue['state']} · {body_length} body characters · {issue['html_url']}",
            )

        for reference in scenario["pull_requests"]:
            number = int(reference["number"])
            pull_request = github.get(f"/repos/{_repo_path(source)}/pulls/{number}")
            if pull_request.get("title") != reference["title"]:
                report.fail(
                    f"pull request #{number}",
                    f"Title changed to: {pull_request.get('title')}",
                )
                continue
            if not pull_request.get("merged_at"):
                report.fail(
                    f"pull request #{number}", "Pinned product PR is not merged."
                )
                continue
            report.pass_(
                f"pull request #{number}",
                f"merged · {pull_request['html_url']}",
            )

        documentation = scenario["documentation"]
        root = documentation["root"].strip("/")
        target_path = documentation["target_path"].strip("/")
        github.get(_contents_path(source, root))
        report.pass_("documentation root", f"{source}/{root}")
        source_page = github.get(_contents_path(source, target_path))
        publish_page = github.get(_contents_path(publish, target_path))
        report.pass_(
            "documentation target",
            f"update {target_path} · source blob {str(source_page.get('sha', ''))[:10]}",
        )
        for label, page in (("upstream", source_page), ("fork", publish_page)):
            content = _decode_github_content(page)
            present = [
                snippet
                for snippet in documentation.get("expected_missing_snippets", [])
                if snippet in content
            ]
            if present:
                report.fail(
                    f"documentation gap:{label}",
                    f"Scenario may be resolved; found: {', '.join(present)}",
                )
            else:
                report.pass_(
                    f"documentation gap:{label}",
                    "All expected CLI omissions are still absent",
                )

        for check in scenario.get("implementation_checks", []):
            implementation = github.get(_contents_path(source, check["path"]))
            content = _decode_github_content(implementation)
            missing = [
                snippet
                for snippet in check.get("required_snippets", [])
                if snippet not in content
            ]
            if missing:
                report.fail(
                    f"implementation:{Path(check['path']).name}",
                    f"Missing expected source markers: {', '.join(missing)}",
                )
            else:
                report.pass_(
                    f"implementation:{Path(check['path']).name}",
                    "Expected shipped CLI options are present",
                )

        open_pull_requests = github.get(
            f"/repos/{_repo_path(publish)}/pulls",
            {"state": "open", "per_page": "100"},
        )
        demo_pull_requests = [
            item
            for item in open_pull_requests
            if str((item.get("head") or {}).get("ref", "")).startswith("docshound/")
        ]
        if demo_pull_requests:
            numbers = ", ".join(f"#{item['number']}" for item in demo_pull_requests)
            report.warn(
                "existing demo PRs",
                f"{numbers} already open in {publish}; new runs still use unique branches.",
            )
        else:
            report.pass_("existing demo PRs", "No open docshound/* pull requests")

        if (
            github.rate_limit_remaining is not None
            and github.rate_limit_remaining >= 100
        ):
            report.pass_(
                "GitHub rate limit", f"{github.rate_limit_remaining} requests remaining"
            )
        elif github.rate_limit_remaining is not None:
            report.warn(
                "GitHub rate limit",
                f"Only {github.rate_limit_remaining} requests remaining",
            )
    except (KeyError, RuntimeError) as exc:
        report.fail("GitHub API", str(exc))


def _decode_github_content(payload: dict[str, Any]) -> str:
    encoded = str(payload.get("content") or "").replace("\n", "")
    if not encoded:
        raise RuntimeError("GitHub did not return file content for a scenario check")
    try:
        return base64.b64decode(encoded).decode("utf-8")
    except (ValueError, UnicodeDecodeError) as exc:
        raise RuntimeError("GitHub returned invalid file content") from exc


def check_model(
    report: Report,
    scenario: dict[str, Any],
    environment: dict[str, str],
    scenario_name: str,
    *,
    skip_live_probe: bool,
) -> None:
    api_key = environment.get("MERGE_GATEWAY_API_KEY", "").strip()
    if not api_key:
        report.fail(
            "Merge Gateway",
            "Set MERGE_GATEWAY_API_KEY in .env; a browser-only key is lost on restart.",
        )
        return
    report.pass_("Merge Gateway", "Credential configured (value redacted)")
    if skip_live_probe:
        report.warn("agent scenario probe", "Skipped by command-line option")
        return
    model = (scenario.get("model") or {}).get(
        "primary",
        environment.get("MERGE_GATEWAY_PRIMARY_MODEL", "google/gemini-3.7-flash"),
    )
    probe_environment = dict(environment)
    probe_environment["DOCSHOUND_DEMO_SCENARIO"] = scenario_name
    probe_environment["MERGE_GATEWAY_PRIMARY_MODEL"] = model
    probe_environment["PYTHONPATH"] = str(ROOT / "backend")
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            """
import asyncio
import json
import os

from opentelemetry import trace as trace_api

from app.tools.cluster import cluster_issues
from app.tools.github import research_pull_requests, research_repo
from app.tracing import run_traced, set_run_output, setup_tracing, traced_run


async def main():
    repository = os.environ['DOCSHOUND_PREFLIGHT_REPOSITORY']
    run_id = f"demo-preflight-{os.environ['DOCSHOUND_DEMO_SCENARIO']}"
    tracing_enabled = setup_tracing()
    with traced_run(run_id, repository) as span:
        issues, pull_requests = await asyncio.gather(
            run_traced(
                "research_repo",
                run_id,
                repository,
                research_repo,
                repository,
                50,
            ),
            run_traced(
                "research_pull_requests",
                run_id,
                repository,
                research_pull_requests,
                repository,
                50,
            ),
        )
        findings = await run_traced(
            "cluster_issues",
            run_id,
            repository,
            cluster_issues,
            issues,
            pull_requests,
            repository,
        )
        set_run_output(span, {
            "issues": issues,
            "pull_requests": pull_requests,
            "clusters": findings,
            "docs_sources": [],
            "errors": [],
        })
    source_refs = [
        f"{source.source_repo}#{source.number}"
        for source in [*issues, *pull_requests]
    ]
    covered_refs = [
        reference
        for finding in findings
        for reference in [*finding.issue_refs, *finding.pr_refs]
    ]
    provider = trace_api.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush()
    print(json.dumps({
        "source_refs": source_refs,
        "covered_refs": covered_refs,
        "finding_count": len(findings),
        "tracing_enabled": tracing_enabled,
    }))


asyncio.run(main())
""",
        ],
        cwd=ROOT,
        env={
            **probe_environment,
            "DOCSHOUND_PREFLIGHT_REPOSITORY": scenario["source_repository"],
        },
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    if probe.returncode != 0:
        detail = (probe.stderr or probe.stdout).strip().splitlines()[-1]
        report.fail("agent scenario probe", detail)
        return
    try:
        payload = json.loads(probe.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError) as exc:
        report.fail("agent scenario probe", f"Invalid probe output: {exc}")
        return
    source_refs = set(payload.get("source_refs") or [])
    covered_refs = set(payload.get("covered_refs") or [])
    missing = sorted(source_refs - covered_refs)
    if missing:
        report.fail(
            "agent scenario probe",
            f"Agent omitted pinned sources: {', '.join(missing)}",
        )
        return
    report.pass_(
        "agent scenario probe",
        f"{len(source_refs)}/{len(source_refs)} sources represented in "
        f"{payload.get('finding_count', 0)} findings via {model}",
    )
    export_error = next(
        (
            line.strip()
            for line in probe.stderr.splitlines()
            if "Failed to export span batch" in line
            or "Exception while exporting Span" in line
        ),
        None,
    )
    if not payload.get("tracing_enabled"):
        report.fail("trace export", "Tracing was not enabled in the agent process")
    elif export_error:
        report.fail("trace export", export_error)
    else:
        report.pass_("trace export", "The canonical OTLP trace batch was submitted")


def check_tracing(
    report: Report,
    environment: dict[str, str],
    scenario_name: str,
    *,
    skip_collector_connect: bool,
) -> None:
    sdk_disabled = environment.get("OTEL_SDK_DISABLED", "false").lower() == "true"
    if sdk_disabled:
        report.fail(
            "OpenInference export",
            "OTEL_SDK_DISABLED is true; remove it or set it to false.",
        )
    if (
        environment.get("LANGSMITH_API_KEY") or environment.get("LANGCHAIN_API_KEY")
    ) and not (
        environment.get("LANGSMITH_PROJECT") or environment.get("LANGCHAIN_PROJECT")
    ):
        environment.setdefault("LANGSMITH_PROJECT", f"docshound-{scenario_name}-demo")
    config = resolve_trace_export_config(environment)
    if config is None and not sdk_disabled:
        report.fail(
            "OpenInference export",
            "Set LANGSMITH_API_KEY, or configure an explicit OTLP endpoint.",
        )
    elif config is not None:
        if config.destination == "langsmith":
            project = (
                environment.get("LANGSMITH_PROJECT")
                or environment.get("LANGCHAIN_PROJECT")
                or f"docshound-{scenario_name}-demo"
            )
            report.pass_(
                "OpenInference export",
                f"LangSmith project {project} via OTLP",
            )
        else:
            report.pass_(
                "OpenInference export",
                f"Explicit OTLP destination at {config.endpoint}",
            )

        if skip_collector_connect:
            report.warn(
                "trace connection",
                f"Configured at {config.endpoint}; connection skipped",
            )
        else:
            parsed = urllib.parse.urlparse(config.endpoint)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname:
                report.fail(
                    "trace connection",
                    f"Invalid OTLP endpoint: {config.endpoint}",
                )
            else:
                port = parsed.port or (443 if parsed.scheme == "https" else 80)
                try:
                    with socket.create_connection((parsed.hostname, port), timeout=3):
                        pass
                    report.pass_(
                        "trace connection",
                        f"{parsed.hostname}:{port} is reachable",
                    )
                except OSError as exc:
                    report.fail(
                        "trace connection",
                        f"Cannot reach {parsed.hostname}:{port}: {exc}",
                    )

        if config.destination == "langsmith" and not skip_collector_connect:
            api_endpoint = (
                environment.get("LANGSMITH_ENDPOINT")
                or environment.get("LANGCHAIN_ENDPOINT")
                or DEFAULT_LANGSMITH_ENDPOINT
            ).rstrip("/")
            auth_headers = {
                "Accept": "application/json",
                "x-api-key": config.headers["x-api-key"],
            }
            workspace_id = environment.get("LANGSMITH_WORKSPACE_ID", "").strip()
            if workspace_id:
                auth_headers["x-tenant-id"] = workspace_id
            try:
                _request_json(
                    f"{api_endpoint}/sessions?limit=1",
                    headers=auth_headers,
                )
                report.pass_("LangSmith credential", "Accepted (value redacted)")
            except RuntimeError as exc:
                report.fail("LangSmith credential", str(exc))

    test_environment = dict(os.environ)
    test_environment["PYTHONPATH"] = str(ROOT / "backend")
    # Prevent test imports from exporting to a developer's configured backend
    # while leaving the OpenTelemetry SDK active for the in-memory span tests.
    for variable in (
        "LANGSMITH_API_KEY",
        "LANGCHAIN_API_KEY",
        "OTEL_EXPORTER_OTLP_ENDPOINT",
        "OTEL_EXPORTER_OTLP_TRACES_ENDPOINT",
    ):
        test_environment[variable] = ""
    test_environment.pop("OTEL_SDK_DISABLED", None)
    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "unittest",
            "backend.tests.test_tracing",
            "backend.tests.test_tracing_config",
            "backend.tests.test_cluster_tracing",
            "-q",
        ],
        cwd=ROOT,
        env=test_environment,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    if completed.returncode == 0:
        report.pass_(
            "trace self-test", "OpenInference schema, hierarchy, and source refs passed"
        )
    else:
        detail = (completed.stderr or completed.stdout).strip().splitlines()[-1]
        report.fail("trace self-test", detail)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("scenario", nargs="?", default="opencode")
    parser.add_argument(
        "--skip-model-probe",
        action="store_true",
        help="Check that the Gateway key exists without making a completion request.",
    )
    parser.add_argument(
        "--skip-collector-connect",
        action="store_true",
        help="Check that tracing is configured without making a network request.",
    )
    parser.add_argument(
        "--require-free-app-ports",
        action="store_true",
        help="Fail when the backend or frontend development port is already in use.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    report = Report()
    print(f"DocsHound demo preflight · scenario {args.scenario}\n")
    try:
        scenario = _load_scenario(args.scenario)
        report.pass_("scenario", f"{scenario['title']} · pinned live GitHub sources")
        if scenario.get("include_recent_activity", True):
            report.warn(
                "activity selection",
                "Recent activity is enabled, so findings may vary between rehearsals.",
            )
        else:
            count = len(scenario["issues"]) + len(scenario["pull_requests"])
            report.pass_(
                "activity selection",
                f"Pinned-only mode · exactly {count} live GitHub sources",
            )
    except RuntimeError as exc:
        report.fail("scenario", str(exc))
        report.print()
        return 1

    environment, loaded_files = _load_environment()
    if loaded_files:
        report.pass_(
            "environment",
            ", ".join(str(path.relative_to(ROOT)) for path in loaded_files),
        )
    else:
        report.warn(
            "environment", "No .env files found; using process environment only"
        )

    check_toolchain(
        report,
        require_free_app_ports=args.require_free_app_ports,
    )
    check_github(report, scenario, environment)
    check_tracing(
        report,
        environment,
        args.scenario,
        skip_collector_connect=args.skip_collector_connect,
    )
    check_model(
        report,
        scenario,
        environment,
        args.scenario,
        skip_live_probe=args.skip_model_probe,
    )
    report.print()
    if report.failed:
        print("\nPreflight blocked. Fix the FAIL items, then run this command again.")
        return 1
    print(f"\nReady. Start with: ./demo/run.sh {args.scenario}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
