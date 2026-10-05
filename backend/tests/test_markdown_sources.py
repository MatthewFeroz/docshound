import unittest

from app.approved_documents import ApprovedDocument, document_body_markdown
from app.documentation_prs import (
    _build_document_content,
    _build_updated_document_content,
)
from app.tools.cluster import _remove_generated_source_section

EVIDENCE = "- [Issue #12: Retry behavior](https://github.com/acme/product/issues/12)"


class MarkdownSourceTests(unittest.TestCase):
    def test_legitimate_content_is_preserved(self) -> None:
        examples = [
            "# Guide\n\n## Sources of truth\n\nUse the catalog.",
            "# Guide\n\nSee ## Sources for the required input format.",
            f"# Guide\n\n```markdown\n## Sources\n\n{EVIDENCE}\n```",
            f"# Guide\n\n~~~markdown\n## Sources\n\n{EVIDENCE}\n~~~",
            f"# Guide\n\n````markdown\n```\n## Sources\n\n{EVIDENCE}\n````",
            f"# Guide\n\n    ## Sources\n\n{EVIDENCE}",
            "# Guide\n\n## Sources\n\nRequests come from the upstream catalog.",
            "# Guide\n\n## Sources\n\n- [Input catalog](https://docs.example.com/catalog)",
            f"# Guide\n\n## Sources\n\n{EVIDENCE}\n\n## Configuration\n\nSet retries.",
            "# Guide\n\n## Source issues to investigate\n\nInspect retries.",
            "# Guide\n\n## Sources",
            f"# Guide\n\n## Sources\n\n    {EVIDENCE}",
            f"# Guide\n\n## Sources\n\n\t{EVIDENCE}",
            f"# Guide\n\n```markdown\n## Sources\n\n{EVIDENCE}",
        ]
        for strip in (document_body_markdown, _remove_generated_source_section):
            for source in examples:
                with self.subTest(function=strip.__name__, source=source):
                    self.assertEqual(strip(source), source)

    def test_trailing_generated_appendices_are_removed(self) -> None:
        body = "# Guide\n\nUse bounded retries."
        for heading in (
            "## Sources",
            "## Source GitHub issues",
            "## Source issues",
            "## Sources ##",
        ):
            for strip in (document_body_markdown, _remove_generated_source_section):
                with self.subTest(function=strip.__name__, heading=heading):
                    self.assertEqual(strip(f"{body}\n\n{heading}\n\n{EVIDENCE}"), body)

    def test_code_example_survives_before_the_generated_appendix(self) -> None:
        body = f"# Guide\n\n```markdown\n## Sources\n\n{EVIDENCE}\n```"
        source = f"{body}\n\n## Sources\n\n{EVIDENCE}"
        for strip in (document_body_markdown, _remove_generated_source_section):
            self.assertEqual(strip(source), body)

    def test_all_generated_evidence_labels_and_empty_source_fallback_are_removed(self) -> None:
        body = "# Guide\n\nUse bounded retries."
        examples = [
            "- [Merged PR #42](https://example.com/pr/42)",
            "- [Open docs PR #43: Retries](https://example.com/pr/43)",
            "- [Existing docs: Retry guide](https://docs.example.com/retries)",
            "- [#12: Retry behavior](https://github.com/acme/product/issues/12)",
            "- No linked repository sources were available.",
        ]
        for appendix in examples:
            with self.subTest(appendix=appendix):
                self.assertEqual(
                    document_body_markdown(f"{body}\n\n## Sources\n\n{appendix}"), body
                )

    def test_line_endings_in_the_body_are_preserved(self) -> None:
        body = "# Guide\r\n\r\nUse bounded retries."
        self.assertEqual(
            document_body_markdown(f"{body}\r\n\r\n## Sources\r\n\r\n{EVIDENCE}"), body
        )

    def test_published_pages_keep_sources_of_truth_and_complete_code_examples(self) -> None:
        body = (
            "# Guide\n\n## Sources of truth\n\nUse the catalog.\n\n"
            "```markdown\n## Sources\n\n- Example input\n```"
        )
        document = ApprovedDocument(
            slug="guide-run-1",
            run_id="run",
            gap_index=0,
            repo="acme/product",
            title="Guide",
            summary="Use the catalog.",
            markdown=f"{body}\n\n## Sources\n\n{EVIDENCE}",
            source_issues=[],
            approved_at="2026-10-04T00:00:00+00:00",
            updated_at="2026-10-04T00:00:00+00:00",
        )

        self.assertEqual(_build_document_content(document, "markdown"), f"{body}\n")
        self.assertIn(body, _build_document_content(document, "mdx"))
        updated = _build_updated_document_content("# Existing guide\n", document)
        self.assertIn("## Sources of truth\n\nUse the catalog.", updated)
        self.assertIn("```markdown\n## Sources\n\n- Example input\n```", updated)
        self.assertNotIn(EVIDENCE, updated)


if __name__ == "__main__":
    unittest.main()
