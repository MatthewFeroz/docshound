from typing import Any, Iterable

from fastapi.templating import Jinja2Templates


_SPONSOR_ICONS = {
    "github": "GitHub",
    "openai": "OpenAI",
    "clickhouse": "ClickHouse",
    "senso": "Senso",
    "nimble": "Nimble",
    "datadog": "Datadog",
}

_TOOL_LABELS = {
    "research_repo": "research_repo",
    "cluster_issues": "cluster_issues",
    "store_results": "store_results",
    "publish_citeable": "publish_citeable",
    "search_official_docs": "search_official_docs",
    "nimble_search": "nimble_search",
}


def _render(templates: Jinja2Templates, name: str, ctx: dict[str, Any]) -> str:
    template = templates.get_template(name)
    return template.render(**ctx).strip()


def _timeline(templates: Jinja2Templates, **ctx: Any) -> str:
    return _render(templates, "_partials/timeline_event.html", ctx)


def _oob_dot(sponsor: str, accent_class: str | None = None) -> str:
    label = _SPONSOR_ICONS.get(sponsor, sponsor.title())
    extra = f" {accent_class}" if accent_class else ""
    return (
        f'<span class="dot lit{extra}" id="dot-{sponsor}" hx-swap-oob="outerHTML">'
        f'<span class="dot-mark"></span>{label}</span>'
    )


def _oob_stats(
    issues: int,
    gaps: int,
    duration_ms: float | None = None,
    extra: str = "",
) -> str:
    parts = [f"<strong>{issues}</strong> issues", f"<strong>{gaps}</strong> gaps"]
    if duration_ms is not None:
        parts.append(f"{duration_ms / 1000:.1f}s")
    if extra:
        parts.append(extra)
    body = " · ".join(parts)
    return f'<div id="stats" class="stats" hx-swap-oob="outerHTML">{body}</div>'


def _oob_gaps_count(count: int) -> str:
    return (
        f'<span class="panel-sub" id="gaps-count" hx-swap-oob="outerHTML">'
        f"{count} found</span>"
    )


def _hide_empty() -> str:
    return (
        '<div class="gaps-empty" id="gaps-empty" hx-swap-oob="outerHTML" hidden></div>'
    )


def render_events(
    event: dict[str, Any],
    templates: Jinja2Templates,
    run_id: str,
) -> Iterable[dict[str, str]]:
    etype = event.get("type")

    if etype == "run_started":
        yield {
            "event": "timeline",
            "data": _timeline(
                templates,
                kind="system",
                icon="●",
                label=f"run started · {event['repo']}",
                detail=event["run_id"][:8],
                meta=None,
            ),
        }
        yield {"event": "oob", "data": _oob_dot("datadog", "lit-datadog")}
        return

    if etype == "agent_decision":
        reason = event.get("reason") or ""
        action = event.get("action") or "?"
        yield {
            "event": "timeline",
            "data": _timeline(
                templates,
                kind="decision",
                icon="◆",
                label=f"agent decision → {action}",
                detail=reason,
                meta=None,
            ),
        }
        if "fallback" not in reason.lower() and "not set" not in reason.lower():
            yield {"event": "oob", "data": _oob_dot("openai")}
        return

    if etype == "tool_start":
        name = event.get("name", "")
        sponsor = event.get("sponsor")
        yield {
            "event": "timeline",
            "data": _timeline(
                templates,
                kind="tool-start",
                icon="▸",
                label=_TOOL_LABELS.get(name, name),
                detail=f"sponsor: {sponsor}" if sponsor else None,
                meta=None,
            ),
        }
        if sponsor:
            accent = (
                "lit-senso" if sponsor == "senso"
                else "lit-datadog" if sponsor == "datadog"
                else None
            )
            yield {"event": "oob", "data": _oob_dot(sponsor, accent)}
        return

    if etype == "tool_end":
        name = event.get("name", "")
        duration_ms = event.get("duration_ms")
        status = event.get("status")
        if status == "error":
            yield {
                "event": "timeline",
                "data": _timeline(
                    templates,
                    kind="error",
                    icon="✕",
                    label=f"{name} failed",
                    detail=event.get("error") or "",
                    meta=f"{duration_ms} ms" if duration_ms is not None else None,
                ),
            }
        else:
            yield {
                "event": "timeline",
                "data": _timeline(
                    templates,
                    kind="tool-end",
                    icon="✓",
                    label=f"{name} ok",
                    detail=None,
                    meta=f"{duration_ms} ms" if duration_ms is not None else None,
                ),
            }
        return

    if etype == "issues_fetched":
        count = event.get("count", 0)
        yield {
            "event": "timeline",
            "data": _timeline(
                templates,
                kind="success",
                icon="◉",
                label=f"{count} issues fetched",
                detail=None,
                meta=None,
            ),
        }
        yield {"event": "oob", "data": _oob_stats(issues=count, gaps=0)}
        return

    if etype == "gap_found":
        cluster = event["cluster"]
        index = event["index"]
        ctx = {"cluster": cluster, "index": index, "run_id": run_id}
        yield {
            "event": "gap_card",
            "data": _render(templates, "_partials/gap_card.html", ctx),
        }
        yield {"event": "oob", "data": _hide_empty()}
        yield {"event": "oob", "data": _oob_gaps_count(index + 1)}
        return

    if etype == "docs_sources_found":
        count = event.get("count", 0)
        sources = event.get("sources") or []
        detail = ", ".join(source.get("title", "source") for source in sources[:2])
        yield {
            "event": "timeline",
            "data": _timeline(
                templates,
                kind="success",
                icon="◈",
                label=f"{count} official docs sources checked",
                detail=detail or None,
                meta=None,
            ),
        }
        yield {"event": "oob", "data": _oob_dot("nimble")}
        return

    if etype == "gap_published":
        # already handled via direct response from /publish endpoint
        yield {
            "event": "timeline",
            "data": _timeline(
                templates,
                kind="success",
                icon="↗",
                label="published citeable to Senso",
                detail=event.get("url", ""),
                meta=None,
            ),
        }
        yield {"event": "oob", "data": _oob_dot("senso", "lit-senso")}
        return

    if etype == "run_completed":
        status = event.get("status", "completed")
        kind = "error" if status == "failed" else "success"
        icon = "✕" if kind == "error" else "✓"
        yield {
            "event": "timeline",
            "data": _timeline(
                templates,
                kind=kind,
                icon=icon,
                label=f"run {status}",
                detail=None,
                meta=None,
            ),
        }
        yield {
            "event": "oob",
            "data": _oob_stats(
                issues=event.get("issues_scraped", 0),
                gaps=event.get("clusters_found", 0),
                extra=f"status: {status}",
            ),
        }
        return
