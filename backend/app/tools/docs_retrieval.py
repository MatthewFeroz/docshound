import math
import re
from collections import Counter
from dataclasses import dataclass
from heapq import heappush, heapreplace

from app.state import GapCluster
from app.tools.docs_discovery import DocumentPage

_STOP_WORDS = {
    "about",
    "after",
    "also",
    "and",
    "are",
    "been",
    "before",
    "can",
    "clear",
    "documentation",
    "does",
    "for",
    "from",
    "gap",
    "have",
    "how",
    "into",
    "more",
    "need",
    "needs",
    "recent",
    "related",
    "should",
    "that",
    "the",
    "their",
    "there",
    "these",
    "this",
    "through",
    "using",
    "users",
    "what",
    "when",
    "where",
    "which",
    "with",
}


@dataclass(frozen=True)
class RetrievedChunk:
    gap_index: int
    gap_name: str
    page: DocumentPage
    text: str
    score: float
    matched_terms: tuple[str, ...]
    rerank_score: float | None = None
    semantic_score: float | None = None


@dataclass(frozen=True)
class _ChunkSignals:
    tokens: Counter[str]
    page_signal: str
    lowered_text: str
    source_type: str


@dataclass(frozen=True)
class LexicalRanking:
    ranked: dict[int, list[RetrievedChunk]]
    candidates: dict[int, list[RetrievedChunk]]


def rank_chunks_for_gaps(
    clusters: list[GapCluster],
    pages: list[DocumentPage],
    per_gap: int = 3,
    *,
    dedupe_pages: bool = True,
) -> dict[int, list[RetrievedChunk]]:
    if dedupe_pages:
        return rank_lexical_evidence(clusters, pages, per_gap=max(1, per_gap)).ranked
    limit = (
        per_gap
        if per_gap >= 0
        else sum(len(chunk_document(page.text)) for page in pages)
    )
    candidates = rank_lexical_evidence(
        clusters, pages, per_gap=0, candidate_limit=limit
    ).candidates
    return {index: chunks[:per_gap] for index, chunks in candidates.items()}


def rank_lexical_evidence(
    clusters: list[GapCluster],
    pages: list[DocumentPage],
    per_gap: int = 3,
    candidate_limit: int = 0,
) -> LexicalRanking:
    """Score once, retaining the best page excerpts and a bounded candidate pool."""
    queries = [
        (cluster, _query_terms(cluster), _important_phrases(cluster))
        for cluster in clusters
    ]
    # Only the best passage per URL can appear in page-deduplicated results.
    best_pages = {index: {} for index in range(len(queries))}
    top_candidates = {index: [] for index in range(len(queries))}
    if not queries:
        return LexicalRanking({}, {})

    position = 0
    for page in pages:
        page_signal = " ".join(
            [page.title, page.url.rsplit("/", 2)[-1].replace("-", " ")]
        ).lower()
        for chunk in chunk_document(page.text):
            # Reuse each passage's tokens across gaps without retaining a corpus index.
            signals = _ChunkSignals(
                Counter(_tokenize(chunk)), page_signal, chunk.lower(), page.source_type
            )
            for gap_index, (cluster, terms, phrases) in enumerate(queries):
                score, matched = _score_chunk(terms, phrases, signals)
                if score <= 0:
                    continue
                candidate = RetrievedChunk(
                    gap_index=gap_index,
                    gap_name=cluster.name,
                    page=page,
                    text=chunk,
                    score=score,
                    matched_terms=tuple(sorted(matched)),
                )
                # Earlier passages win ties, matching the original stable sort.
                key = (
                    score,
                    len(matched),
                    page.source_type in {"official_docs", "repo_docs"},
                    -position,
                )
                if per_gap:
                    previous = best_pages[gap_index].get(page.url)
                    if previous is None or key > previous[0]:
                        best_pages[gap_index][page.url] = (key, candidate)
                if candidate_limit:
                    heap = top_candidates[gap_index]
                    entry = (key, candidate)
                    if len(heap) < candidate_limit:
                        heappush(heap, entry)
                    elif key > heap[0][0]:
                        heapreplace(heap, entry)
            position += 1

    return LexicalRanking(
        ranked={
            index: [
                chunk
                for _, chunk in sorted(
                    rows.values(), key=lambda row: row[0], reverse=True
                )
            ][:per_gap]
            for index, rows in best_pages.items()
        },
        candidates={
            index: [
                chunk for _, chunk in sorted(heap, key=lambda row: row[0], reverse=True)
            ]
            for index, heap in top_candidates.items()
        },
    )


def chunk_document(
    text: str,
    max_chars: int = 1400,
    overlap_chars: int = 180,
) -> list[str]:
    normalized = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not normalized:
        return []

    paragraphs = [
        " ".join(paragraph.split())
        for paragraph in re.split(r"\n\s*\n|\n(?=[A-Z][^\n]{0,100}$)", normalized)
        if paragraph.strip()
    ]
    chunks: list[str] = []
    current = ""
    for paragraph in paragraphs:
        if len(paragraph) > max_chars:
            sentences = re.split(r"(?<=[.!?])\s+", paragraph)
        else:
            sentences = [paragraph]
        for sentence in sentences:
            candidate = f"{current}\n\n{sentence}".strip() if current else sentence
            if current and len(candidate) > max_chars:
                chunks.append(current)
                overlap = current[-overlap_chars:].lstrip()
                current = f"{overlap} {sentence}".strip()
            else:
                current = candidate
    if current:
        chunks.append(current)
    return [chunk[: max_chars + overlap_chars] for chunk in chunks if len(chunk) >= 50]


def source_confidence(chunk: RetrievedChunk) -> float:
    score_component = chunk.score / (chunk.score + 12)
    term_component = min(0.2, len(chunk.matched_terms) * 0.035)
    return round(min(0.95, 0.42 + score_component * 0.35 + term_component), 3)


def _query_terms(cluster: GapCluster) -> set[str]:
    text = " ".join(
        [
            cluster.name,
            cluster.summary,
            cluster.recurring_question,
            cluster.draft_title or "",
        ]
    )
    counts = Counter(_tokenize(text))
    return {
        token
        for token, _ in counts.most_common(24)
        if token not in _STOP_WORDS and len(token) >= 3
    }


def _score_chunk(
    terms: set[str],
    important_phrases: set[str],
    signals: _ChunkSignals,
) -> tuple[float, set[str]]:
    matched = {
        term for term in terms if term in signals.tokens or term in signals.page_signal
    }
    if not matched:
        return 0, set()

    score = 0.0
    for term in matched:
        frequency = signals.tokens.get(term, 0)
        score += 1.0 + math.log1p(frequency)
        if term in signals.page_signal:
            score += 2.2

    score += sum(3.0 for phrase in important_phrases if phrase in signals.lowered_text)
    score += min(3.0, len(matched) * 0.35)
    if signals.source_type in {"official_docs", "repo_docs"}:
        score += 0.5
    return round(score, 4), matched


def _important_phrases(cluster: GapCluster) -> set[str]:
    phrases: set[str] = set()
    for value in (cluster.name, cluster.recurring_question):
        tokens = [
            token
            for token in _tokenize(value)
            if token not in _STOP_WORDS and len(token) >= 3
        ]
        for size in (2, 3):
            phrases.update(
                " ".join(tokens[index : index + size])
                for index in range(len(tokens) - size + 1)
            )
    return phrases


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9_.+-]*", text.lower())
