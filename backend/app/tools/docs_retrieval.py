import math
import re
from collections import Counter
from dataclasses import dataclass

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


def rank_chunks_for_gaps(
    clusters: list[GapCluster],
    pages: list[DocumentPage],
    per_gap: int = 3,
    *,
    dedupe_pages: bool = True,
) -> dict[int, list[RetrievedChunk]]:
    page_chunks = [
        (page, chunk) for page in pages for chunk in chunk_document(page.text)
    ]
    ranked: dict[int, list[RetrievedChunk]] = {}

    for gap_index, cluster in enumerate(clusters):
        terms = _query_terms(cluster)
        candidates: list[RetrievedChunk] = []
        for page, chunk in page_chunks:
            score, matched = _score_chunk(terms, cluster, page, chunk)
            if score <= 0:
                continue
            candidates.append(
                RetrievedChunk(
                    gap_index=gap_index,
                    gap_name=cluster.name,
                    page=page,
                    text=chunk,
                    score=score,
                    matched_terms=tuple(sorted(matched)),
                )
            )

        candidates.sort(
            key=lambda candidate: (
                candidate.score,
                len(candidate.matched_terms),
                candidate.page.source_type in {"official_docs", "repo_docs"},
            ),
            reverse=True,
        )
        ranked[gap_index] = (
            _dedupe_pages(candidates, per_gap) if dedupe_pages else candidates[:per_gap]
        )

    return ranked


def chunk_document(
    text: str,
    max_chars: int = 1400,
    overlap_chars: int = 180,
) -> list[str]:
    if max_chars < 1 or not 0 <= overlap_chars < max_chars:
        raise ValueError("Expected positive chunk size and smaller nonnegative overlap")
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
                overlap = current[-overlap_chars:].lstrip() if overlap_chars else ""
                current = f"{overlap} {sentence}".strip()
            else:
                current = candidate
            # Some pages contain a single long sentence, table row, or code block.
            # Window those passages rather than truncating all text after the first chunk.
            while len(current) > max_chars + overlap_chars:
                boundary = current.rfind(" ", 0, max_chars + 1)
                if boundary < max_chars // 2 or boundary <= overlap_chars:
                    boundary = max_chars
                chunks.append(current[:boundary].rstrip())
                current = current[boundary - overlap_chars :].lstrip()
    if current:
        chunks.append(current)
    return [chunk for chunk in chunks if len(chunk) >= 50 or len(chunks) > 1]


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
    cluster: GapCluster,
    page: DocumentPage,
    chunk: str,
) -> tuple[float, set[str]]:
    chunk_tokens = Counter(_tokenize(chunk))
    page_signal = " ".join(
        [
            page.title,
            page.url.rsplit("/", 2)[-1].replace("-", " "),
        ]
    ).lower()
    matched = {term for term in terms if term in chunk_tokens or term in page_signal}
    if not matched:
        return 0, set()

    score = 0.0
    for term in matched:
        frequency = chunk_tokens.get(term, 0)
        score += 1.0 + math.log1p(frequency)
        if term in page_signal:
            score += 2.2

    important_phrases = _important_phrases(cluster)
    lowered_chunk = chunk.lower()
    score += sum(3.0 for phrase in important_phrases if phrase in lowered_chunk)
    score += min(3.0, len(matched) * 0.35)
    if page.source_type in {"official_docs", "repo_docs"}:
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


def _dedupe_pages(
    candidates: list[RetrievedChunk],
    limit: int,
) -> list[RetrievedChunk]:
    selected: list[RetrievedChunk] = []
    seen_urls: set[str] = set()
    for candidate in candidates:
        if candidate.page.url in seen_urls:
            continue
        seen_urls.add(candidate.page.url)
        selected.append(candidate)
        if len(selected) >= limit:
            break
    return selected


def _tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9_.+-]*", text.lower())
