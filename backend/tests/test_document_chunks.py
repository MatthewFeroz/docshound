import unittest

from app.state import GapCluster
from app.tools.docs_discovery import DocumentPage
from app.tools.docs_retrieval import chunk_document, rank_chunks_for_gaps


class DocumentChunkTests(unittest.TestCase):
    def test_long_single_sentence_preserves_late_evidence(self):
        words = [f"field{index:04d}" for index in range(600)]
        text = " ".join(words) + " credential rotation requires an administrator"
        chunks = chunk_document(text)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 1580 for chunk in chunks))
        self.assertTrue(
            all(any(word in chunk.split() for chunk in chunks) for word in words)
        )
        self.assertIn("credential rotation requires an administrator", chunks[-1])
        cluster = GapCluster(
            name="Credential rotation",
            summary="Explain credential rotation permissions",
            recurring_question="Who can perform credential rotation?",
            issue_numbers=[1],
            severity="medium",
            confidence=0.8,
        )
        page = DocumentPage("Reference", "https://example.com/reference", text)
        ranked = rank_chunks_for_gaps([cluster], [page])
        self.assertEqual(len(ranked[0]), 1)
        self.assertIn(
            "credential rotation requires an administrator", ranked[0][0].text
        )

    def test_unbroken_text_uses_bounded_overlapping_windows(self):
        chunks = chunk_document("x" * 4000, max_chars=100, overlap_chars=20)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 120 for chunk in chunks))
        self.assertEqual(sum(map(len, chunks)) - 20 * (len(chunks) - 1), 4000)

    def test_small_tail_is_retained_without_overlap(self):
        text = "a" * 100 + "b" * 100 + "tail"
        chunks = chunk_document(text, max_chars=100, overlap_chars=0)
        self.assertEqual("".join(chunks), text)

    def test_large_overlap_advances_past_a_word_boundary_inside_the_overlap(self):
        text = "x" * 99 + " " + "z" * 300
        chunks = chunk_document(text, max_chars=100, overlap_chars=99)
        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 199 for chunk in chunks))
        self.assertTrue(chunks[-1].endswith("z" * 100))

    def test_short_documents_and_sentence_sized_passages_are_unchanged(self):
        self.assertEqual(chunk_document("short"), [])
        text = "Documentation describes credential rotation. " * 20
        self.assertEqual(chunk_document(text), [text.strip()])

    def test_invalid_window_sizes_fail_instead_of_looping(self):
        for max_chars, overlap_chars in [(0, 0), (100, -1), (100, 100)]:
            with self.subTest(max_chars=max_chars, overlap_chars=overlap_chars):
                with self.assertRaises(ValueError):
                    chunk_document("documentation" * 100, max_chars, overlap_chars)
