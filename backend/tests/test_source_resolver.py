import base64
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx2 as httpx

from app.source_resolver import resolve_documentation_sources


def _encoded(value: str) -> str:
    return base64.b64encode(value.encode()).decode()


class DocumentationSourceResolverTests(unittest.IsolatedAsyncioTestCase):
    async def test_readme_docs_link_selects_same_repository_root(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/repos/acme/product":
                return httpx.Response(
                    200,
                    json={
                        "default_branch": "main",
                        "homepage": "https://product.example.com",
                    },
                )
            if request.url.path == "/repos/acme/product/git/trees/main":
                return httpx.Response(
                    200,
                    json={
                        "tree": [
                            {"path": "docs/start.md", "type": "blob"},
                            {"path": "docs/configuration.md", "type": "blob"},
                            {"path": "docs/reference.mdx", "type": "blob"},
                            {"path": "packages/internal/README.md", "type": "blob"},
                        ]
                    },
                )
            if request.url.path == "/repos/acme/product/readme":
                return httpx.Response(
                    200,
                    json={
                        "content": _encoded(
                            "# Product\n\n[Documentation](docs/)"
                        )
                    },
                )
            return httpx.Response(404, json={"message": "not found"})

        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            with patch(
                "app.source_resolver.get_settings",
                return_value=SimpleNamespace(github_token=None),
            ):
                result = await resolve_documentation_sources(
                    "acme/product",
                    client=client,
                    fetch_websites=False,
                )

        self.assertEqual(result.selected_source.repo, "acme/product")
        self.assertEqual(result.selected_source.root, "docs")
        self.assertEqual(result.selected_source.page_count, 3)
        self.assertEqual(result.selected_source.discovered_by, "readme_docs_link")
        self.assertEqual(result.documentation_activity_repos, [])

    async def test_edit_on_github_discovers_separate_documentation_repo(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path == "/repos/acme/product":
                return httpx.Response(
                    200,
                    json={
                        "default_branch": "main",
                        "homepage": "https://docs.acme.dev",
                    },
                )
            if request.url.path == "/repos/acme/product/git/trees/main":
                return httpx.Response(200, json={"tree": []})
            if request.url.path == "/repos/acme/product/readme":
                return httpx.Response(
                    200,
                    json={"content": _encoded("[Docs](https://docs.acme.dev)")},
                )
            if request.url.path == "/repos/acme/docs-site":
                return httpx.Response(200, json={"default_branch": "main"})
            if request.url.path == "/repos/acme/docs-site/git/trees/main":
                return httpx.Response(
                    200,
                    json={
                        "tree": [
                            {
                                "path": "content/en/docs/getting-started.md",
                                "type": "blob",
                            },
                            {
                                "path": "content/en/docs/reference.mdx",
                                "type": "blob",
                            },
                        ]
                    },
                )
            return httpx.Response(404, json={"message": "not found"})

        html = (
            '<a href="https://github.com/acme/docs-site/edit/main/'
            'content/en/docs/getting-started.md">Edit this page on GitHub</a>'
        )
        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            with (
                patch(
                    "app.source_resolver.get_settings",
                    return_value=SimpleNamespace(github_token=None),
                ),
                patch(
                    "app.source_resolver._fetch_public_html",
                    new=AsyncMock(return_value=(html, "https://docs.acme.dev")),
                ),
            ):
                result = await resolve_documentation_sources(
                    "acme/product",
                    client=client,
                )

        self.assertEqual(result.selected_source.repo, "acme/docs-site")
        self.assertEqual(result.selected_source.root, "content/en/docs")
        self.assertEqual(result.selected_source.page_count, 2)
        self.assertEqual(result.selected_source.discovered_by, "edit_on_github")
        self.assertEqual(result.documentation_activity_repos, ["acme/docs-site"])


if __name__ == "__main__":
    unittest.main()
