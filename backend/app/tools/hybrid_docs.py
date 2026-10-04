"""Website crawling and hybrid passage retrieval shared by the restored review flow."""

import asyncio

import httpx

from app.config import Settings
from app.tools.docs_discovery import (
    DocumentPage,
    discover_docs_root,
    discover_document_urls,
    fetch_document_pages,
)
from app.tools.docs_retrieval import rank_chunks_for_gaps
from app.tools.nvidia_embed import retrieve_semantic, select_pages
from app.tools.nvidia_rerank import rerank_gap
from app.tracing import observe_operation, publish_span_progress


async def website_pages(repo: str, docs_url: str | None) -> list[DocumentPage]:
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        root = await observe_operation(
            "discover_docs_root",
            discover_docs_root,
            client,
            repo,
            docs_url,
            output_details=lambda value: {"docs_root": value},
        )
        if not root:
            return []
        urls = await observe_operation(
            "discover_document_urls",
            discover_document_urls,
            client,
            root,
            output_details=lambda value: {"page_count": len(value)},
        )
        return await observe_operation(
            "fetch_document_pages",
            fetch_document_pages,
            client,
            urls,
            progress=publish_span_progress,
            output_details=lambda value: {"page_count": len(value)},
            trace_outputs=lambda pages: {
                "documents": [
                    {"page_content": page.text, "metadata": {"source": page.url}}
                    for page in pages
                ]
            },
        )


async def rank_evidence(clusters, pages, settings: Settings, per_gap: int):
    ranked = await observe_operation(
        "rank_docs_for_gaps",
        rank_chunks_for_gaps,
        clusters,
        pages,
        per_gap=per_gap,
        input_details={"gap_count": len(clusters), "page_count": len(pages)},
        output_details=lambda value: {"excerpt_count": sum(map(len, value.values()))},
    )
    if not (settings.nvidia_embed_enabled or settings.nvidia_rerank_enabled):
        return ranked
    candidates = rank_chunks_for_gaps(
        clusters,
        pages,
        per_gap=settings.nvidia_rerank_candidates,
        dedupe_pages=False,
    )
    async with httpx.AsyncClient() as client:
        if settings.nvidia_embed_enabled:
            result = await observe_operation(
                "retrieve_semantic_docs",
                retrieve_semantic,
                client,
                clusters,
                pages,
                candidates,
                settings,
                limit=settings.nvidia_rerank_candidates,
                input_details={
                    "model": settings.nvidia_embed_model,
                    "page_count": len(pages),
                },
                output_summary=lambda value: f"{value.status}: {value.reason}",
                output_details=lambda value: value.details(),
                trace_outputs=lambda value: value.details(),
            )
            if result.status == "hybrid":
                candidates = result.candidates
                ranked = {
                    i: select_pages(chunks, limit=per_gap)
                    for i, chunks in candidates.items()
                }
        if settings.nvidia_rerank_enabled:

            async def rerank(index, cluster):
                return await observe_operation(
                    "rerank_docs_for_gap",
                    rerank_gap,
                    client,
                    cluster,
                    candidates.get(index, []),
                    ranked.get(index, []),
                    settings,
                    per_gap=per_gap,
                    input_summary=cluster.name,
                    output_summary=lambda value: f"{value.status}: {value.reason}",
                    output_details=lambda value: value.details(),
                    trace_outputs=lambda value: value.details(),
                )

            # Independent gap requests share the client, with at most four in flight.
            for start in range(0, len(clusters), 4):
                results = await asyncio.gather(
                    *(
                        rerank(index, clusters[index])
                        for index in range(start, min(start + 4, len(clusters)))
                    ),
                    return_exceptions=True,
                )
                for index, result in enumerate(results, start=start):
                    if isinstance(result, BaseException):
                        raise result
                    ranked[index] = result.chunks
    return ranked
