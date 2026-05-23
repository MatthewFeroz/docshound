import json
import re
from collections import defaultdict

from openai import AsyncOpenAI

from app.config import get_settings
from app.state import GapCluster, Issue


KEYWORDS = {
    "installation": ["install", "setup", "pip", "npm", "dependency", "build"],
    "authentication": ["auth", "token", "login", "permission", "credential", "401"],
    "configuration": ["config", "environment", "env", "setting", "option"],
    "deployment": ["deploy", "docker", "kubernetes", "server", "production"],
    "errors": ["error", "exception", "traceback", "failed", "crash", "bug"],
    "api usage": ["api", "example", "usage", "how to", "docs", "documentation"],
}


async def cluster_issues(issues: list[Issue]) -> list[GapCluster]:
    settings = get_settings()
    if settings.openai_api_key and len(issues) >= 2:
        try:
            return await _cluster_with_llm(issues)
        except Exception:
            return _cluster_heuristically(issues)
    return _cluster_heuristically(issues)


async def _cluster_with_llm(issues: list[Issue]) -> list[GapCluster]:
    settings = get_settings()
    client = AsyncOpenAI(api_key=settings.openai_api_key)
    issue_payload = [
        {
            "number": issue.number,
            "title": issue.title,
            "body": (issue.body or "")[:1200],
            "labels": issue.labels,
            "comments_count": issue.comments_count,
        }
        for issue in issues[:60]
    ]

    response = await client.chat.completions.create(
        model=settings.openai_model,
        response_format={"type": "json_object"},
        messages=[
            {
                "role": "system",
                "content": (
                    "You cluster GitHub issues into recurring documentation gaps. "
                    "Return JSON only with a top-level 'clusters' array. Each cluster "
                    "must have name, summary, recurring_question, issue_numbers, "
                    "severity low|medium|high, and confidence 0..1."
                ),
            },
            {
                "role": "user",
                "content": json.dumps({"issues": issue_payload}),
            },
        ],
    )
    raw = response.choices[0].message.content or "{}"
    data = json.loads(raw)
    return [GapCluster.model_validate(item) for item in data.get("clusters", [])[:8]]


def _cluster_heuristically(issues: list[Issue]) -> list[GapCluster]:
    buckets: dict[str, list[Issue]] = defaultdict(list)
    for issue in issues:
        text = f"{issue.title} {issue.body or ''}".lower()
        matched = False
        for name, words in KEYWORDS.items():
            if any(word in text for word in words):
                buckets[name].append(issue)
                matched = True
        if not matched and re.search(r"\?|how|why|what|where|when", text):
            buckets["general questions"].append(issue)

    clusters: list[GapCluster] = []
    for name, bucket in sorted(buckets.items(), key=lambda item: len(item[1]), reverse=True):
        if len(bucket) < 2:
            continue
        issue_numbers = [issue.number for issue in bucket[:10]]
        example_titles = "; ".join(issue.title for issue in bucket[:3])
        severity = "high" if len(bucket) >= 5 else "medium"
        clusters.append(
            GapCluster(
                name=f"{name.title()} documentation gap",
                summary=f"{len(bucket)} recent issues appear related to {name}: {example_titles}",
                recurring_question=f"Users need clearer documentation about {name}.",
                issue_numbers=issue_numbers,
                severity=severity,
                confidence=min(0.9, 0.45 + len(bucket) / 20),
            )
        )
    return clusters[:8]


def attach_review_drafts(clusters: list[GapCluster], issues: list[Issue]) -> list[GapCluster]:
    issue_by_number = {issue.number: issue for issue in issues}
    for cluster in clusters:
        related = [
            issue_by_number[number]
            for number in cluster.issue_numbers
            if number in issue_by_number
        ]
        title = f"{cluster.name}: {cluster.recurring_question}".strip()
        title = title[:110]
        issue_lines = "\n".join(
            f"- #{issue.number}: [{issue.title}]({issue.url})" for issue in related[:8]
        )
        if not issue_lines:
            issue_lines = "- No linked issues were available for this draft."

        cluster.draft_title = title
        cluster.draft_summary = (
            f"Draft documentation response for {len(related)} GitHub issues in "
            f"{cluster.name.lower()}."
        )
        cluster.draft_markdown = f"""# {title}

## What users are asking
{cluster.summary}

Recurring question: {cluster.recurring_question}

## Recommended documentation update
Add a focused docs section that answers the recurring question directly, explains the expected configuration or behavior, and links back to the relevant first-party documentation.

## Source GitHub issues
{issue_lines}

## Review notes
- Severity: {cluster.severity}
- Confidence: {cluster.confidence:.0%}
- Generated by the Docs Gap Agent for human review before publishing.
"""
    return clusters
