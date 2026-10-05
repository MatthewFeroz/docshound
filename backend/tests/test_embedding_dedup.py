import json
import unittest
from unittest.mock import patch

import httpx

from app.config import Settings
from app.state import GapCluster
from app.tools.docs_discovery import DocumentPage
from app.tools.nvidia_embed import _CACHE, _passage_vectors, retrieve_semantic


class EmbeddingDedupTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        _CACHE.clear()
        self.config = Settings(_env_file=None, nvidia_api_key="test-secret")
        self.requests = []

    def handler(self, request):
        body = json.loads(request.content)
        self.requests.append(body)
        return httpx.Response(
            200,
            json={
                "data": [
                    {"index": index, "embedding": [len(text), 1]}
                    for index, text in reversed(list(enumerate(body["input"])))
                ]
            },
        )

    async def test_cold_duplicate_passages_are_embedded_once_and_restore_input_order(
        self,
    ):
        inputs = ["short", "a longer passage", "short"] * 16
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(self.handler)
        ) as client:
            vectors, hits = await _passage_vectors(client, inputs, self.config)
            cached, warm_hits = await _passage_vectors(client, inputs, self.config)
        self.assertEqual(len(self.requests), 1)
        self.assertEqual(self.requests[0]["input"], ["short", "a longer passage"])
        self.assertEqual(hits, 0)
        self.assertEqual(warm_hits, 48)
        self.assertEqual(cached, vectors)
        self.assertEqual(len(vectors), len(inputs))
        self.assertEqual(vectors[0], vectors[2])
        self.assertNotEqual(vectors[0], vectors[1])
        self.assertEqual(len(_CACHE), 2)

    async def test_mixed_hits_and_expired_duplicates_keep_freshness_and_counts(self):
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(self.handler)
        ) as client:
            with patch("app.tools.nvidia_embed.monotonic", return_value=1000):
                await _passage_vectors(client, ["cached"], self.config)
            with patch("app.tools.nvidia_embed.monotonic", return_value=1500):
                _, hits = await _passage_vectors(
                    client, ["cached", "new", "cached", "new"], self.config
                )
            with patch("app.tools.nvidia_embed.monotonic", return_value=1600):
                _, expired_hits = await _passage_vectors(
                    client, ["cached", "new", "cached"], self.config
                )
        self.assertEqual(hits, 2)
        self.assertEqual(expired_hits, 1)
        self.assertEqual(
            [body["input"] for body in self.requests], [["cached"], ["new"], ["cached"]]
        )

    async def test_duplicate_inputs_preserve_distinct_source_urls_in_semantic_results(
        self,
    ):
        docs = [
            DocumentPage(
                "Rotation",
                f"https://example.com/{i}",
                "Credential rotation requires an administrator using the console.",
            )
            for i in range(3)
        ]
        gap = GapCluster(
            name="Credential rotation",
            summary="Explain credential rotation",
            recurring_question="Who rotates credentials?",
            issue_numbers=[1],
            severity="medium",
            confidence=0.8,
        )
        async with httpx.AsyncClient(
            transport=httpx.MockTransport(self.handler)
        ) as client:
            result = await retrieve_semantic(client, [gap], docs, {}, self.config)
        self.assertEqual(result.status, "hybrid")
        self.assertEqual(result.passage_count, 3)
        self.assertEqual(
            {chunk.page.url for chunk in result.candidates[0]},
            {page.url for page in docs},
        )
        self.assertEqual(len(self.requests[0]["input"]), 1)
        self.assertEqual(self.requests[1]["input_type"], "query")
