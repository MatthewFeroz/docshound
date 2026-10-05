import inspect
import unittest
from dataclasses import replace
from unittest.mock import AsyncMock, patch

from app.config import Settings
from app.state import GapCluster
from app.tools import docs_retrieval
from app.tools.docs_discovery import DocumentPage
from app.tools.docs_retrieval import chunk_document, rank_chunks_for_gaps
from app.tools.hybrid_docs import rank_evidence
from app.tools.nvidia_embed import SemanticResult


def gaps() -> list[GapCluster]:
    return [
        GapCluster(
            name="MCP server environment variables",
            summary="Users cannot tell how to pass environment variables to MCP servers.",
            recurring_question="How do I configure environment variables for an MCP server?",
            issue_numbers=[101],
            severity="high",
            confidence=0.91,
        ),
        GapCluster(
            name="Interface themes",
            summary="Customize the color theme and syntax highlighting.",
            recurring_question="How do I change the interface appearance?",
            issue_numbers=[102],
            severity="medium",
            confidence=0.8,
        ),
    ]


def pages() -> list[DocumentPage]:
    mcp_text = (
        "Configure an MCP server with a local command. Use the env mapping to pass "
        "environment variables such as API tokens. Each key is the variable name "
        "and each value is passed to the server process when it starts."
    )
    return [
        DocumentPage(
            title="MCP servers",
            url="https://example.com/docs/mcp-servers",
            text=mcp_text,
            source_type="official_docs",
        ),
        DocumentPage(
            title="MCP servers",
            url="https://example.com/docs/alternate",
            text=mcp_text,
            source_type="repo_docs",
        ),
        DocumentPage(
            title="Themes",
            url="https://example.com/docs/themes",
            text=(
                "Choose a color theme, customize syntax highlighting, and change "
                "the appearance of the application interface."
            ),
        ),
    ]


class LexicalRankingTests(unittest.TestCase):
    def test_preserves_scores_matched_terms_and_tie_order(self) -> None:
        ranked = rank_chunks_for_gaps(gaps(), pages())
        self.assertEqual(
            [(chunk.page.url, chunk.score, chunk.matched_terms) for chunk in ranked[0]],
            [
                (
                    "https://example.com/docs/mcp-servers",
                    23.5643,
                    ("configure", "environment", "mcp", "pass", "server", "variables"),
                ),
                (
                    "https://example.com/docs/alternate",
                    23.5643,
                    ("configure", "environment", "mcp", "pass", "server", "variables"),
                ),
            ],
        )
        self.assertEqual(
            [(chunk.page.url, chunk.score) for chunk in ranked[1]],
            [("https://example.com/docs/themes", 18.5089)],
        )

    def test_tokenization_grows_with_chunks_and_gaps_instead_of_their_product(self):
        documents = pages()
        clusters = gaps() * 8
        chunk_count = sum(len(chunk_document(page.text)) for page in documents)
        with patch.object(
            docs_retrieval, "_tokenize", wraps=docs_retrieval._tokenize
        ) as tokenize:
            rank_chunks_for_gaps(clusters, documents)
        # Each gap has one query and two phrase inputs. Each passage is read once.
        self.assertEqual(tokenize.call_count, chunk_count + 3 * len(clusters))

    def test_empty_gaps_skip_document_processing(self):
        with patch.object(docs_retrieval, "chunk_document") as chunk:
            self.assertEqual(rank_chunks_for_gaps([], pages()), {})
        chunk.assert_not_called()
        self.assertEqual(rank_chunks_for_gaps(gaps(), []), {0: [], 1: []})


async def observe_locally(name, operation, *args, **kwargs):
    for key in (
        "input_details",
        "output_details",
        "output_summary",
        "trace_outputs",
        "input_summary",
    ):
        kwargs.pop(key, None)
    result = operation(*args, **kwargs)
    return await result if inspect.isawaitable(result) else result


class HybridRankingTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_fallback_keeps_pages_beyond_the_candidate_limit(self):
        documents = pages()
        documents[0] = replace(documents[0], text="\n\n".join([documents[0].text] * 25))
        clusters = gaps()[:1]
        expected = rank_chunks_for_gaps(clusters, documents, per_gap=3)
        captured = []

        async def semantic(client, clusters, pages, candidates, settings, limit):
            captured.append(candidates)
            return SemanticResult(candidates, "fallback", "Unavailable", "test")

        with (
            patch("app.tools.hybrid_docs.observe_operation", observe_locally),
            patch("app.tools.hybrid_docs.retrieve_semantic", semantic),
            patch(
                "app.tools.hybrid_docs.rank_lexical_evidence",
                wraps=docs_retrieval.rank_lexical_evidence,
            ) as rank,
        ):
            actual = await rank_evidence(
                clusters,
                documents,
                Settings(
                    _env_file=None,
                    nvidia_embed_enabled=True,
                    nvidia_rerank_candidates=3,
                ),
                per_gap=3,
            )

        self.assertEqual(actual, expected)
        self.assertEqual(len(actual[0]), 2)
        self.assertEqual(len(captured[0][0]), 3)
        self.assertEqual(
            {chunk.page.url for chunk in captured[0][0]}, {documents[0].url}
        )
        rank.assert_called_once()

    async def test_keyword_only_search_preserves_page_selection(self):
        with patch("app.tools.hybrid_docs.observe_operation", observe_locally):
            actual = await rank_evidence(
                gaps(), pages(), Settings(_env_file=None), per_gap=1
            )
        self.assertEqual(actual, rank_chunks_for_gaps(gaps(), pages(), per_gap=1))

    async def test_hybrid_search_does_not_rescore_whole_repository_documents(self):
        from app.tools.docs import RepositoryDocument, search_official_docs

        cluster = gaps()[0]
        page = pages()[0]
        document = RepositoryDocument("docs/mcp.md", page.title, page.text, page.url)
        ranked = rank_chunks_for_gaps([cluster], [page])
        with (
            patch("app.tools.docs._configured_github_token", return_value=None),
            patch("app.tools.docs.llm_is_configured", return_value=False),
            patch("app.tools.docs.observe_operation", observe_locally),
            patch(
                "app.tools.docs._load_relevant_repository_documents",
                AsyncMock(return_value=[document]),
            ),
            patch("app.tools.docs.rank_evidence", AsyncMock(return_value=ranked)),
            patch("app.tools.docs._rank_documents") as rescore,
        ):
            clusters, sources, inspected = await search_official_docs(
                "acme/repo", None, [cluster], client=object(), repo_docs_max_files=100
            )
        rescore.assert_not_called()
        self.assertEqual(inspected, 1)
        self.assertEqual(
            clusters[0].documentation_coverage.recommended_path, "docs/mcp.md"
        )
        self.assertEqual(sources[0].url, page.url)


if __name__ == "__main__":
    unittest.main()
