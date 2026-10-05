"""Nemotron semantic retrieval with bounded batches, cache, and lexical rank fusion."""

import asyncio
import hashlib
import math
from collections import OrderedDict
from dataclasses import dataclass, replace
from itertools import zip_longest
from time import monotonic

import httpx

from app.config import Settings
from app.state import GapCluster
from app.tools.docs_discovery import DocumentPage
from app.tools.docs_retrieval import RetrievedChunk, chunk_document
from app.usage import track_model_call

BATCH_SIZE = 16
CACHE_SIZE = 2048
CACHE_TTL_SECONDS = 600
# Only passage vectors are cached; keys include endpoint, model, and exact input hash.
_CACHE: OrderedDict[tuple[str, str, str], tuple[float, tuple[float, ...]]] = (
    OrderedDict()
)


@dataclass
class SemanticResult:
    candidates: dict[int, list[RetrievedChunk]]
    status: str
    reason: str
    model: str
    passage_count: int = 0
    omitted_passages: int = 0
    cache_hits: int = 0

    def details(self) -> dict:
        return {
            "status": self.status,
            "reason": self.reason,
            "model": self.model,
            "passage_count": self.passage_count,
            "omitted_passages": self.omitted_passages,
            "cache_hits": self.cache_hits,
            "sources": {
                str(index): [
                    {"url": chunk.page.url, "semantic_score": chunk.semantic_score}
                    for chunk in chunks
                ]
                for index, chunks in self.candidates.items()
            },
        }


async def retrieve_semantic(
    client: httpx.AsyncClient,
    clusters: list[GapCluster],
    pages: list[DocumentPage],
    lexical: dict[int, list[RetrievedChunk]],
    settings: Settings,
    limit: int = 20,
) -> SemanticResult:
    result = SemanticResult(lexical, "fallback", "", settings.nvidia_embed_model)
    if not clusters or not pages:
        result.status, result.reason = "skipped", "No gaps or documentation pages"
        return result
    if (
        not settings.nvidia_api_key
        or not settings.nvidia_api_key.get_secret_value().strip()
    ):
        result.reason = "NVIDIA_API_KEY is not configured"
        return result

    # Round-robin across pages so a long first page cannot consume the entire corpus budget.
    per_page = [[(page, text) for text in chunk_document(page.text)] for page in pages]
    corpus = [
        pair for row in zip_longest(*per_page) for pair in row if pair is not None
    ]
    result.omitted_passages = max(0, len(corpus) - settings.nvidia_embed_max_passages)
    corpus = corpus[: settings.nvidia_embed_max_passages]
    result.passage_count = len(corpus)
    if not corpus:
        result.status, result.reason = "skipped", "No usable documentation passages"
        return result
    inputs = [f"{page.title[:300]}\n{text}" for page, text in corpus]
    queries = [
        "\n".join([cluster.recurring_question, cluster.name, cluster.summary])[:3000]
        for cluster in clusters
    ]
    try:
        async with asyncio.timeout(settings.nvidia_embed_timeout_seconds):
            vectors, result.cache_hits = await _passage_vectors(
                client, inputs, settings
            )
            query_vectors = await _embed(client, queries, "query", settings)
        if any(
            len(vector) != len(query_vectors[0]) for vector in vectors + query_vectors
        ):
            raise ValueError("Embedding dimensions differ")
        hybrid = {}
        for index, (cluster, query) in enumerate(
            zip(clusters, query_vectors, strict=True)
        ):
            semantic = [
                RetrievedChunk(
                    gap_index=index,
                    gap_name=cluster.name,
                    page=page,
                    text=text,
                    score=0,
                    matched_terms=(),
                    semantic_score=sum(
                        a * b for a, b in zip(query, vector, strict=True)
                    ),
                )
                for (page, text), vector in zip(corpus, vectors, strict=True)
            ]
            semantic.sort(key=lambda chunk: chunk.semantic_score, reverse=True)
            hybrid[index] = _fuse(lexical.get(index, []), semantic[:limit], limit)
        result.candidates = hybrid
        result.status = "hybrid"
        result.reason = "Combined keyword and Nemotron semantic search"
    except httpx.HTTPStatusError as exc:
        result.reason = f"NVIDIA HTTP {exc.response.status_code}; using keyword search"
    except httpx.RequestError, TimeoutError:
        result.reason = "NVIDIA request failed or timed out; using keyword search"
    except ValueError, TypeError, KeyError, OverflowError:
        result.reason = "Invalid NVIDIA embedding response; using keyword search"
    return result


async def _passage_vectors(
    client: httpx.AsyncClient, inputs: list[str], settings: Settings
) -> tuple[list[tuple[float, ...]], int]:
    keys = [
        (
            settings.nvidia_embed_url,
            settings.nvidia_embed_model,
            hashlib.sha256(s.encode()).hexdigest(),
        )
        for s in inputs
    ]
    found: dict[int, tuple[float, ...]] = {}
    missing: dict[tuple[str, str, str], list[int]] = {}
    for index, key in enumerate(keys):
        cached = _CACHE.get(key)
        if cached and monotonic() - cached[0] < CACHE_TTL_SECONDS:
            found[index] = cached[1]
            _CACHE.move_to_end(key)
        else:
            missing.setdefault(key, []).append(index)
    cache_hits = len(found)
    if missing:
        vectors = await _embed(
            client,
            [inputs[indices[0]] for indices in missing.values()],
            "passage",
            settings,
        )
        for (key, indices), vector in zip(missing.items(), vectors, strict=True):
            for index in indices:
                found[index] = vector
            _CACHE[key] = (monotonic(), vector)
            _CACHE.move_to_end(key)
            while len(_CACHE) > CACHE_SIZE:
                _CACHE.popitem(last=False)
    return [found[index] for index in range(len(inputs))], cache_hits


async def _embed(
    client: httpx.AsyncClient, inputs: list[str], input_type: str, settings: Settings
) -> list[tuple[float, ...]]:
    vectors = []
    # Four bounded batches at a time; gather preserves input order and drains failures.
    for start in range(0, len(inputs), BATCH_SIZE * 4):
        batches = [
            inputs[i : i + BATCH_SIZE]
            for i in range(start, min(start + BATCH_SIZE * 4, len(inputs)), BATCH_SIZE)
        ]
        results = await asyncio.gather(
            *(_embed_batch(client, batch, input_type, settings) for batch in batches),
            return_exceptions=True,
        )
        for result in results:
            if isinstance(result, BaseException):
                raise result
            vectors.extend(result)
    return vectors


async def _embed_batch(
    client: httpx.AsyncClient, inputs: list[str], input_type: str, settings: Settings
) -> list[tuple[float, ...]]:
    vectors = []
    for start in range(0, len(inputs), BATCH_SIZE):
        batch = inputs[start : start + BATCH_SIZE]
        with track_model_call(
            "nvidia", settings.nvidia_embed_model, f"embed_{input_type}"
        ) as usage:
            response = await client.post(
                settings.nvidia_embed_url,
                headers={
                    "Authorization": f"Bearer {settings.nvidia_api_key.get_secret_value()}",
                    "Accept": "application/json",
                },
                json={
                    "model": settings.nvidia_embed_model,
                    "input": batch,
                    "input_type": input_type,
                    "encoding_format": "float",
                    "truncate": "END",
                },
                timeout=15,
                follow_redirects=False,
            )
            response.raise_for_status()
            payload = response.json()
            usage.report(payload.get("usage") if isinstance(payload, dict) else None)
            if not isinstance(payload, dict) or not isinstance(
                payload.get("data"), list
            ):
                raise ValueError("Expected embedding data")
            ordered = {}
            for row in payload["data"]:
                if not isinstance(row, dict):
                    raise ValueError("Invalid embedding row")
                index, embedding = row.get("index"), row.get("embedding")
                if (
                    type(index) is not int
                    or index not in range(len(batch))
                    or index in ordered
                ):
                    raise ValueError("Invalid embedding index")
                if (
                    not isinstance(embedding, list)
                    or not embedding
                    or len(embedding) > 8192
                ):
                    raise ValueError("Invalid embedding vector")
                if any(
                    type(v) not in (int, float) or not math.isfinite(v)
                    for v in embedding
                ):
                    raise ValueError("Invalid embedding values")
                norm = math.hypot(*embedding)
                if not math.isfinite(norm) or norm == 0:
                    raise ValueError("Invalid embedding norm")
                ordered[index] = tuple(v / norm for v in embedding)
            if len(ordered) != len(batch):
                raise ValueError("Incomplete embeddings")
            vectors.extend(ordered[index] for index in range(len(batch)))
    return vectors


def _fuse(
    lexical: list[RetrievedChunk], semantic: list[RetrievedChunk], limit: int
) -> list[RetrievedChunk]:
    # Reciprocal rank fusion combines ranks, not incomparable lexical/cosine scores.
    scores: dict[tuple[str, str], float] = {}
    chunks: dict[tuple[str, str], RetrievedChunk] = {}
    for ranking in (lexical, semantic):
        for rank, chunk in enumerate(ranking, start=1):
            key = (chunk.page.url, chunk.text)
            scores[key] = scores.get(key, 0) + 1 / (60 + rank)
            if key not in chunks:
                chunks[key] = chunk
            elif chunk.semantic_score is not None:
                chunks[key] = replace(chunks[key], semantic_score=chunk.semantic_score)
    return [chunks[key] for key in sorted(scores, key=scores.get, reverse=True)[:limit]]


def select_pages(chunks: list[RetrievedChunk], limit: int = 3) -> list[RetrievedChunk]:
    selected, seen = [], set()
    for chunk in chunks:
        if chunk.page.url not in seen:
            selected.append(chunk)
            seen.add(chunk.page.url)
        if len(selected) == limit:
            break
    return selected
