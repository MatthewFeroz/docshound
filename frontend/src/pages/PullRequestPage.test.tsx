import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";

import type { DocumentPayload } from "../types";
import { PullRequestPage } from "./PullRequestPage";

const apiMocks = vi.hoisted(() => ({
  createPullRequest: vi.fn(),
  getDocument: vi.fn(),
  previewPullRequest: vi.fn(),
}));

vi.mock("../api", () => ({
  api: apiMocks,
  assetUrl: (path: string) => path,
}));

const permissionMessage =
  "DocsHound could not create a fork of upstream/pi for matt (403: Resource " +
  "not accessible). Create the fork once on GitHub or reconnect a token that " +
  "permits fork creation; DocsHound will detect and reuse it automatically on " +
  "the next attempt. No branch was created.";

const payload: DocumentPayload = {
  document: {
    slug: "theme-cli-override-run12345-1",
    run_id: "run12345",
    gap_index: 0,
    repo: "upstream/pi",
    title: "Theme CLI Override",
    summary: "Explain the theme override.",
    markdown: "# Theme CLI Override",
    source_issues: [],
    approved_at: "2026-08-15T00:00:00Z",
    updated_at: "2026-08-15T00:00:00Z",
  },
  body_markdown: "# Theme CLI Override",
  documentation_change: {
    document_slug: "theme-cli-override-run12345-1",
    target_repo: "upstream/pi",
    publish_repo: null,
    base_branch: "main",
    branch_name: "docshound/theme-cli-override-run12345",
    file_path: "docs/theme-cli-override.md",
    file_format: "markdown",
    detected_by: "manual path",
    edit_action: "create_page",
    content: "# Theme CLI Override",
    patch: "+# Theme CLI Override",
    existing_sha: null,
    status: "preview_ready",
    pr_number: null,
    pr_url: null,
    error: null,
    created_at: "2026-08-15T00:00:00Z",
    updated_at: "2026-08-15T00:00:00Z",
  },
  suggested_file_path: "docs/theme-cli-override.md",
  suggested_action: "create_page",
  suggested_target_repo: "upstream/pi",
  write_enabled: true,
};

function renderPage() {
  render(
    <MemoryRouter
      initialEntries={["/documents/theme-cli-override-run12345-1/pull-request"]}
    >
      <Routes>
        <Route
          path="/documents/:slug/pull-request"
          element={<PullRequestPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("PullRequestPage", () => {
  beforeEach(() => {
    apiMocks.getDocument.mockResolvedValue(payload);
    apiMocks.createPullRequest.mockRejectedValue(new Error(permissionMessage));
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("keeps a publication failure visible with an actionable next step", async () => {
    renderPage();

    fireEvent.click(
      await screen.findByRole("button", { name: "Publish upstream PR" }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not complete the request");
    expect(alert).toHaveTextContent("could not create a fork");
    expect(alert).toHaveTextContent("Create the fork once on GitHub");
    expect(alert).toHaveTextContent("reuse it automatically");
    expect(screen.getByText("Publication needs attention")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Follow the guidance above, refresh the preview, and try again.",
      ),
    ).toBeInTheDocument();
  });

  it("opens the upstream comparison when GitHub needs browser confirmation", async () => {
    apiMocks.createPullRequest.mockResolvedValue({
      ...payload,
      documentation_change: {
        ...payload.documentation_change!,
        publish_repo: "matt/pi",
        status: "branch_ready",
        pr_url:
          "https://github.com/upstream/pi/compare/main...matt:docshound/theme-cli-override-run12345?expand=1",
        error:
          "The documentation branch is ready in matt/pi. GitHub requires confirmation.",
      },
    });
    renderPage();

    fireEvent.click(
      await screen.findByRole("button", { name: "Publish upstream PR" }),
    );

    expect(
      await screen.findByText("Branch ready for an upstream pull request"),
    ).toBeInTheDocument();
    expect(screen.getByText("matt/pi")).toBeInTheDocument();
    expect(
      screen.getByRole("link", { name: "Open upstream PR" }),
    ).toHaveAttribute("href", expect.stringContaining("upstream/pi/compare"));
  });
});
