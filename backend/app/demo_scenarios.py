import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from app.config import get_settings


_SCENARIO_NAME = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
_REPOSITORY = re.compile(r"^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$")
_SCENARIO_DIRECTORY = Path(__file__).resolve().parents[2] / "demo" / "scenarios"


@dataclass(frozen=True)
class PinnedReference:
    number: int
    title: str
    rationale: str
    related_pull_requests: tuple[int, ...]


@dataclass(frozen=True)
class DemoScenario:
    name: str
    title: str
    source_repository: str
    publish_repository: str
    issues: tuple[PinnedReference, ...]
    pull_requests: tuple[PinnedReference, ...]
    include_recent_activity: bool
    documentation_root: str
    target_path: str


def active_demo_scenario() -> DemoScenario | None:
    name = get_settings().docshound_demo_scenario
    return load_demo_scenario(name) if name else None


def pinned_issue_numbers(repository: str) -> tuple[int, ...]:
    scenario = active_demo_scenario()
    if not scenario or scenario.source_repository.lower() != repository.lower():
        return ()
    return tuple(reference.number for reference in scenario.issues)


def pinned_pull_request_numbers(repository: str) -> tuple[int, ...]:
    scenario = active_demo_scenario()
    if not scenario or scenario.source_repository.lower() != repository.lower():
        return ()
    return tuple(reference.number for reference in scenario.pull_requests)


def include_recent_activity(repository: str) -> bool:
    """Keep production research broad unless an active demo opts into pinned-only mode."""
    scenario = active_demo_scenario()
    if not scenario or scenario.source_repository.lower() != repository.lower():
        return True
    return scenario.include_recent_activity


def pinned_issue_relationships(repository: str) -> dict[int, tuple[int, ...]]:
    """Return researched issue-to-implementation links for an active demo."""
    scenario = active_demo_scenario()
    if not scenario or scenario.source_repository.lower() != repository.lower():
        return {}
    return {
        reference.number: reference.related_pull_requests
        for reference in scenario.issues
    }


def documentation_target_path(repository: str) -> str | None:
    """Return the researched edit target for either side of an active demo."""
    scenario = active_demo_scenario()
    if not scenario:
        return None
    repositories = {
        scenario.source_repository.lower(),
        scenario.publish_repository.lower(),
    }
    return scenario.target_path if repository.lower() in repositories else None


@lru_cache(maxsize=8)
def load_demo_scenario(name: str) -> DemoScenario:
    if not _SCENARIO_NAME.fullmatch(name):
        raise RuntimeError(
            "DOCSHOUND_DEMO_SCENARIO must contain only lowercase letters, "
            "numbers, underscores, and hyphens."
        )
    path = _SCENARIO_DIRECTORY / f"{name}.json"
    if not path.is_file():
        raise RuntimeError(f"Demo scenario not found: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Could not read demo scenario {path}: {exc}") from exc

    source_repository = _required_repository(payload, "source_repository", path)
    publish_repository = _required_repository(payload, "publish_repository", path)
    documentation = payload.get("documentation")
    if not isinstance(documentation, dict):
        raise RuntimeError(f"{path}: documentation must be an object")

    issues = _references(payload, "issues", path)
    pull_requests = _references(payload, "pull_requests", path)
    pull_request_numbers = {reference.number for reference in pull_requests}
    for issue in issues:
        unknown = set(issue.related_pull_requests) - pull_request_numbers
        if unknown:
            numbers = ", ".join(str(number) for number in sorted(unknown))
            raise RuntimeError(
                f"{path}: issue {issue.number} links unknown pull requests: {numbers}"
            )

    return DemoScenario(
        name=name,
        title=_required_text(payload, "title", path),
        source_repository=source_repository,
        publish_repository=publish_repository,
        issues=issues,
        pull_requests=pull_requests,
        include_recent_activity=_optional_bool(
            payload,
            "include_recent_activity",
            path,
            default=True,
        ),
        documentation_root=_required_text(documentation, "root", path),
        target_path=_required_text(documentation, "target_path", path),
    )


def _required_repository(
    payload: dict[str, Any], key: str, path: Path
) -> str:
    value = _required_text(payload, key, path)
    if not _REPOSITORY.fullmatch(value):
        raise RuntimeError(f"{path}: {key} must use the owner/repository format")
    return value


def _required_text(payload: dict[str, Any], key: str, path: Path) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise RuntimeError(f"{path}: {key} must be a non-empty string")
    return value.strip()


def _optional_bool(
    payload: dict[str, Any],
    key: str,
    path: Path,
    *,
    default: bool,
) -> bool:
    value = payload.get(key, default)
    if not isinstance(value, bool):
        raise RuntimeError(f"{path}: {key} must be a boolean")
    return value


def _references(
    payload: dict[str, Any], key: str, path: Path
) -> tuple[PinnedReference, ...]:
    values = payload.get(key)
    if not isinstance(values, list):
        raise RuntimeError(f"{path}: {key} must be an array")
    references: list[PinnedReference] = []
    seen: set[int] = set()
    for index, value in enumerate(values):
        if not isinstance(value, dict):
            raise RuntimeError(f"{path}: {key}[{index}] must be an object")
        number = value.get("number")
        if not isinstance(number, int) or number <= 0:
            raise RuntimeError(f"{path}: {key}[{index}].number must be positive")
        if number in seen:
            raise RuntimeError(f"{path}: duplicate {key} number {number}")
        seen.add(number)
        references.append(
            PinnedReference(
                number=number,
                title=_required_text(value, "title", path),
                rationale=_required_text(value, "rationale", path),
                related_pull_requests=_positive_ints(
                    value,
                    "related_pull_requests",
                    path,
                    default=(),
                ),
            )
        )
    return tuple(references)


def _positive_ints(
    payload: dict[str, Any],
    key: str,
    path: Path,
    *,
    default: tuple[int, ...],
) -> tuple[int, ...]:
    values = payload.get(key, list(default))
    if not isinstance(values, list):
        raise RuntimeError(f"{path}: {key} must be an array")
    if any(not isinstance(value, int) or value <= 0 for value in values):
        raise RuntimeError(f"{path}: {key} values must be positive integers")
    if len(values) != len(set(values)):
        raise RuntimeError(f"{path}: {key} values must be unique")
    return tuple(values)
