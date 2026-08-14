import unittest

import httpx

from app.tools.github import GitHubToolError, validate_github_access


class GitHubAccessTests(unittest.IsolatedAsyncioTestCase):
    async def test_validates_activity_and_documentation_permissions(self) -> None:
        requested_paths: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested_paths.append(request.url.path)
            self.assertEqual(request.headers["authorization"], "Bearer github-token")
            payloads = {
                "/user": {"login": "octocat"},
                "/repos/acme/product": {
                    "full_name": "acme/product",
                    "default_branch": "main",
                },
                "/repos/acme/product/issues": [],
                "/repos/acme/product/pulls": [],
                "/repos/acme/product/git/trees/main": {"tree": []},
            }
            payload = payloads.get(request.url.path)
            if payload is None:
                return httpx.Response(404, json={"message": "not found"})
            return httpx.Response(200, json=payload)

        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            account, repo = await validate_github_access(
                "acme/product",
                "github-token",
                client=client,
            )

        self.assertEqual(account, "octocat")
        self.assertEqual(repo, "acme/product")
        self.assertEqual(
            requested_paths,
            [
                "/user",
                "/repos/acme/product",
                "/repos/acme/product/issues",
                "/repos/acme/product/pulls",
                "/repos/acme/product/git/trees/main",
            ],
        )

    async def test_reports_an_invalid_token_without_exposing_it(self) -> None:
        def handler(_request: httpx.Request) -> httpx.Response:
            return httpx.Response(401, json={"message": "bad credentials"})

        async with httpx.AsyncClient(
            base_url="https://api.github.test",
            transport=httpx.MockTransport(handler),
        ) as client:
            with self.assertRaisesRegex(GitHubToolError, "rejected this token"):
                await validate_github_access(
                    "acme/product",
                    "github-token",
                    client=client,
                )


if __name__ == "__main__":
    unittest.main()
