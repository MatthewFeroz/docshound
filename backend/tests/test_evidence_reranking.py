import asyncio
import json
import unittest
from unittest.mock import patch

import httpx

from app.config import Settings
from app.state import GapCluster
from app.tools.docs_discovery import DocumentPage
from app.tools.hybrid_docs import rank_evidence


def gap(index):
    return GapCluster(
        name=f"Credential rotation {index}",
        summary="Explain credential rotation",
        recurring_question="How do I rotate credentials?",
        issue_numbers=[index + 1],
        severity="medium",
        confidence=0.8,
    )


class EvidenceRerankingTests(unittest.IsolatedAsyncioTestCase):
    async def test_requested_limits_order_and_bounded_parallelism(self):
        docs = [
            DocumentPage(
                f"Credentials {index}",
                f"https://example.com/docs/{index}",
                "Credential rotation is supported using the administration console.",
            )
            for index in range(6)
        ]
        config = Settings(
            _env_file=None,
            nvidia_api_key="test-secret",
            nvidia_embed_enabled=False,
            nvidia_rerank_enabled=True,
        )
        for limit in (1, 5):
            active = peak = completed = 0

            async def handler(request):
                nonlocal active, peak, completed
                active += 1
                peak = max(peak, active)
                body = json.loads(request.content)
                try:
                    await asyncio.sleep(0.01)
                    return httpx.Response(
                        200,
                        json={
                            "rankings": [
                                {"index": index, "logit": index}
                                for index in range(len(body["passages"]))
                            ]
                        },
                    )
                finally:
                    active -= 1
                    completed += 1

            client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
            with patch("app.tools.hybrid_docs.httpx.AsyncClient", return_value=client):
                ranked = await rank_evidence(
                    [gap(i) for i in range(9)], docs, config, limit
                )
            self.assertEqual(peak, 4)
            self.assertEqual(completed, 9)
            self.assertEqual(active, 0)
            self.assertEqual(list(ranked), list(range(9)))
            for chunks in ranked.values():
                self.assertEqual(len(chunks), limit)
                self.assertEqual(chunks[0].page.url, docs[-1].url)

    async def test_failed_gap_retains_its_fallback_while_other_gaps_rerank(self):
        docs = [
            DocumentPage(
                "Credentials",
                "https://example.com/docs",
                "Credential rotation is supported using the administration console.",
            )
        ]
        config = Settings(
            _env_file=None,
            nvidia_api_key="test-secret",
            nvidia_embed_enabled=False,
            nvidia_rerank_enabled=True,
        )

        async def handler(request):
            body = json.loads(request.content)
            if "rotation 1" in body["query"]["text"]:
                return httpx.Response(429)
            return httpx.Response(200, json={"rankings": [{"index": 0, "logit": 2}]})

        client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        with patch("app.tools.hybrid_docs.httpx.AsyncClient", return_value=client):
            ranked = await rank_evidence([gap(i) for i in range(3)], docs, config, 1)
        self.assertEqual([ranked[i][0].rerank_score for i in range(3)], [2, None, 2])
