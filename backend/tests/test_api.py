import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from app import approved_documents, documentation_prs, run_store
from app.main import app
from app.runtime_credentials import clear_runtime_credentials
from app.state import RUNS, AgentState, DocumentationCoverage, GapCluster, Issue


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "docshound.db"
        self.original_paths = (
            run_store.DB_PATH,
            approved_documents.DB_PATH,
            documentation_prs.DB_PATH,
        )
        run_store.DB_PATH = self.db_path
        approved_documents.DB_PATH = self.db_path
        documentation_prs.DB_PATH = self.db_path
        RUNS.clear()
        clear_runtime_credentials()
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        (
            run_store.DB_PATH,
            approved_documents.DB_PATH,
            documentation_prs.DB_PATH,
        ) = self.original_paths
        RUNS.clear()
        clear_runtime_credentials()
        self.temp_dir.cleanup()

    def _seed_run(self) -> AgentState:
        now = datetime.now(timezone.utc)
        state = AgentState(
            repo="acme/product",
            status="completed",
            issues=[
                Issue(
                    number=12,
                    title="Document retry behavior",
                    body="How many times should a request retry?",
                    url="https://github.com/acme/product/issues/12",
                    state="open",
                    comments_count=2,
                    created_at=now,
                    updated_at=now,
                )
            ],
            clusters=[
                GapCluster(
                    name="Retry behavior",
                    summary="The retry behavior needs documentation.",
                    recurring_question="How do retries work?",
                    issue_numbers=[12],
                    severity="medium",
                    confidence=0.9,
                    draft_title="Configure retries",
                    draft_markdown="# Configure retries\n\nUse bounded retries.",
                    documentation_coverage=DocumentationCoverage(
                        status="partial",
                        rationale="The reliability page needs retry guidance.",
                        recommended_action="update_page",
                        recommended_path="docs/reliability.md",
                    ),
                )
            ],
        )
        RUNS[state.run_id] = state
        run_store.save_run(state)
        return state

    def test_health_and_cors(self) -> None:
        response = self.client.get("/api/v1/health")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {"status": "ok"})

        preflight = self.client.options(
            "/api/v1/findings",
            headers={
                "Origin": "http://localhost:5173",
                "Access-Control-Request-Method": "GET",
            },
        )
        self.assertEqual(preflight.status_code, 200)
        self.assertEqual(
            preflight.headers["access-control-allow-origin"],
            "http://localhost:5173",
        )

    def test_runtime_config_exposes_models_without_credentials(self) -> None:
        route = SimpleNamespace(
            gateway="merge",
            models=("google/gemini-3.7-flash", "openai/gpt-5.6-luna"),
        )
        with (
            patch("app.main.get_llm_route", return_value=route),
            patch("app.main.write_enabled", return_value=False),
        ):
            response = self.client.get("/api/v1/config")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            response.json(),
            {
                "write_enabled": False,
                "llm_gateway": "merge",
                "llm_primary_model": "google/gemini-3.7-flash",
                "llm_fallback_model": "openai/gpt-5.6-luna",
                "llm_configured": True,
                "credential_input_enabled": True,
            },
        )
        self.assertNotIn("key", response.text.lower())

    def test_local_runtime_credential_is_accepted_without_echoing_it(self) -> None:
        with (
            patch(
                "app.main.get_settings",
                return_value=SimpleNamespace(app_env="development"),
            ),
            patch("app.main.write_enabled", return_value=False),
        ):
            response = self.client.post(
                "/api/v1/config/llm-credential",
                json={"api_key": "temporary-gateway-secret"},
            )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["llm_configured"])
        self.assertEqual(response.json()["llm_gateway"], "merge")
        self.assertNotIn("temporary-gateway-secret", response.text)

    def test_browser_credential_entry_is_disabled_in_production(self) -> None:
        with patch(
            "app.main.get_settings",
            return_value=SimpleNamespace(app_env="production"),
        ):
            response = self.client.post(
                "/api/v1/config/llm-credential",
                json={"api_key": "temporary-gateway-secret"},
            )

        self.assertEqual(response.status_code, 403)
        self.assertIn("disabled in production", response.json()["detail"])

    def test_legacy_run_routes_remain_compatible(self) -> None:
        with patch("app.main.run_agent", new=AsyncMock()):
            created = self.client.post(
                "/runs",
                json={"repo": "acme/product", "limit": 25, "dry_run": True},
            )

        self.assertEqual(created.status_code, 200)
        self.assertEqual(set(created.json()), {"run_id"})
        run_id = created.json()["run_id"]

        fetched = self.client.get(f"/runs/{run_id}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["run_id"], run_id)
        self.assertEqual(fetched.json()["repo"], "acme/product")

        RUNS[run_id].status = "completed"
        events = self.client.get(f"/runs/{run_id}/events.json")
        self.assertEqual(events.status_code, 200)
        self.assertIn("event: run_completed", events.text)
        self.assertIn('"status": "completed"', events.text)

    def test_finding_review_contract(self) -> None:
        state = self._seed_run()

        findings = self.client.get("/api/v1/findings")
        self.assertEqual(findings.status_code, 200)
        self.assertEqual(findings.json()[0]["cluster"]["name"], "Retry behavior")
        self.assertEqual(findings.json()[0]["source_issues"][0]["number"], 12)

        approval = self.client.post(
            f"/api/v1/runs/{state.run_id}/findings/0/approval",
            json={"markdown": "# Configure retries\n\nUse three attempts."},
        )
        self.assertEqual(approval.status_code, 200)
        document = approval.json()["document"]
        self.assertEqual(document["title"], "Configure retries")
        self.assertEqual(document["source_issues"][0]["number"], 12)
        self.assertEqual(approval.json()["suggested_action"], "update_page")
        self.assertEqual(
            approval.json()["suggested_file_path"], "docs/reliability.md"
        )

        fetched = self.client.get(f"/api/v1/documents/{document['slug']}")
        self.assertEqual(fetched.status_code, 200)
        self.assertEqual(fetched.json()["body_markdown"], document["markdown"])

        rejection = self.client.post(
            f"/api/v1/runs/{state.run_id}/findings/0/rejection",
            json={},
        )
        self.assertEqual(rejection.status_code, 200)
        self.assertEqual(rejection.json()["cluster"]["review_status"], "rejected")


if __name__ == "__main__":
    unittest.main()
