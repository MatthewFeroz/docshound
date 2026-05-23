import asyncio
import json
import os
import re
import shutil
from typing import Any

from app.config import get_settings
from app.state import GapCluster
from app.tracing import traced_tool


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:64]


async def publish_citeable(
    run_id: str,
    repo: str,
    cluster: GapCluster,
    dry_run: bool = True,
) -> dict[str, str | None]:
    settings = get_settings()
    with traced_tool("publish_citeable", run_id, repo):
        preview = (
            f"https://cited.md/preview/{_slug(repo)}/{_slug(cluster.name)}"
            f"#run={run_id}"
        )
        if dry_run or not settings.senso_api_key or shutil.which("senso") is None:
            return {
                "url": preview,
                "content_id": None,
                "version_id": None,
                "status": "preview",
            }

        prompt = await _create_prompt(cluster, settings.senso_api_key)
        published = await _publish_draft(
            cluster,
            str(prompt["prompt_id"]),
            settings.senso_api_key,
        )
        url = _published_url(published) or preview
        return {
            "url": url,
            "content_id": published.get("content_id"),
            "version_id": published.get("version_id"),
            "status": published.get("publish_status") or "published",
        }


async def _create_prompt(cluster: GapCluster, api_key: str) -> dict[str, Any]:
    data = {
        "question_text": cluster.recurring_question,
        "type": "evaluation",
        "tags": ["docs-gap-agent", "human-reviewed"],
    }
    return await _run_senso_json(
        [
            "senso",
            "prompts",
            "create",
            "--data",
            json.dumps(data),
            "--output",
            "json",
            "--quiet",
        ],
        api_key,
    )


async def _publish_draft(
    cluster: GapCluster,
    prompt_id: str,
    api_key: str,
) -> dict[str, Any]:
    data = {
        "geo_question_id": prompt_id,
        "seo_title": cluster.draft_title or cluster.name,
        "summary": cluster.draft_summary or cluster.summary,
        "raw_markdown": cluster.draft_markdown or cluster.summary,
    }
    return await _run_senso_json(
        [
            "senso",
            "engine",
            "publish",
            "--data",
            json.dumps(data),
            "--output",
            "json",
            "--quiet",
        ],
        api_key,
    )


async def _run_senso_json(command: list[str], api_key: str) -> dict[str, Any]:
    env = os.environ.copy()
    env["SENSO_API_KEY"] = api_key
    process = await asyncio.create_subprocess_exec(
        *command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )
    stdout, stderr = await process.communicate()
    output = f"{stdout.decode()}\n{stderr.decode()}".strip()
    if process.returncode != 0:
        raise RuntimeError(output or f"Senso command failed: {' '.join(command[:3])}")
    start = output.find("{")
    if start == -1:
        raise RuntimeError(f"Senso command did not return JSON: {output[:300]}")
    return json.loads(output[start:])


def _published_url(data: dict[str, object]) -> str | None:
    destinations = data.get("publish_destinations")
    if isinstance(destinations, list):
        for destination in destinations:
            if isinstance(destination, dict) and destination.get("display_url"):
                return str(destination["display_url"])
    for key in ("display_url", "public_url", "url"):
        if data.get(key):
            return str(data[key])
    content_id = data.get("content_id")
    if content_id:
        return f"https://cited.md/article/{content_id}"
    return None
