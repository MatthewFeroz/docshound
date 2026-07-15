import json
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import bleach
import markdown


DB_PATH = Path(__file__).parent.parent / "data" / "docshound.db"

ALLOWED_TAGS = {
    "a",
    "blockquote",
    "br",
    "code",
    "del",
    "em",
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "hr",
    "li",
    "ol",
    "p",
    "pre",
    "strong",
    "table",
    "tbody",
    "td",
    "th",
    "thead",
    "tr",
    "ul",
}


@dataclass(frozen=True)
class ApprovedDocument:
    slug: str
    run_id: str
    gap_index: int
    repo: str
    title: str
    summary: str
    markdown: str
    source_issues: list[dict[str, str | int]]
    approved_at: str
    updated_at: str


def render_markdown(source: str) -> str:
    rendered = markdown.markdown(
        source,
        extensions=["fenced_code", "tables", "sane_lists"],
        output_format="html",
    )
    return bleach.clean(
        rendered,
        tags=ALLOWED_TAGS,
        attributes={"a": ["href", "title"]},
        protocols={"http", "https", "mailto"},
        strip=True,
    )


def document_body_markdown(source: str) -> str:
    for heading in ("## Sources", "## Source GitHub issues", "## Source issues"):
        if heading in source:
            return source.split(heading, 1)[0].rstrip()
    return source.strip()


def save_approved_document(
    *,
    run_id: str,
    gap_index: int,
    repo: str,
    title: str,
    summary: str,
    markdown_source: str,
    source_issues: list[dict[str, str | int]],
) -> ApprovedDocument:
    now = datetime.now(timezone.utc).isoformat()
    slug = _document_slug(title, run_id, gap_index)
    with _connect() as connection:
        connection.execute(
            """
            INSERT INTO approved_documents (
                slug, run_id, gap_index, repo, title, summary, markdown,
                source_issues_json, approved_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(run_id, gap_index) DO UPDATE SET
                repo = excluded.repo,
                title = excluded.title,
                summary = excluded.summary,
                markdown = excluded.markdown,
                source_issues_json = excluded.source_issues_json,
                updated_at = excluded.updated_at
            """,
            (
                slug,
                run_id,
                gap_index,
                repo,
                title,
                summary,
                markdown_source,
                json.dumps(source_issues),
                now,
                now,
            ),
        )
    document = get_approved_document_for_gap(run_id, gap_index)
    if document is None:
        raise RuntimeError("Approved document was not saved")
    return document


def get_approved_document(slug: str) -> ApprovedDocument | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM approved_documents WHERE slug = ?",
            (slug,),
        ).fetchone()
    return _document_from_row(row) if row else None


def get_approved_document_for_gap(run_id: str, gap_index: int) -> ApprovedDocument | None:
    with _connect() as connection:
        row = connection.execute(
            "SELECT * FROM approved_documents WHERE run_id = ? AND gap_index = ?",
            (run_id, gap_index),
        ).fetchone()
    return _document_from_row(row) if row else None


def _connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(DB_PATH)
    connection.row_factory = sqlite3.Row
    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS approved_documents (
            slug TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            gap_index INTEGER NOT NULL,
            repo TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            markdown TEXT NOT NULL,
            source_issues_json TEXT NOT NULL,
            approved_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(run_id, gap_index)
        )
        """
    )
    return connection


def _document_slug(title: str, run_id: str, gap_index: int) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-") or "document"
    return f"{base[:56].rstrip('-')}-{run_id[:8]}-{gap_index + 1}"


def _document_from_row(row: sqlite3.Row) -> ApprovedDocument:
    return ApprovedDocument(
        slug=row["slug"],
        run_id=row["run_id"],
        gap_index=row["gap_index"],
        repo=row["repo"],
        title=row["title"],
        summary=row["summary"],
        markdown=row["markdown"],
        source_issues=json.loads(row["source_issues_json"]),
        approved_at=row["approved_at"],
        updated_at=row["updated_at"],
    )
