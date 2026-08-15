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
  "DocsHound can read upstream/pi, but the connected GitHub account matt " +
  "cannot publish there. Change Documentation repository to matt/pi, refresh " +
  "the preview, and try again. The connected token must grant Contents: " +
  "read/write and Pull requests: read/write for the destination repository. " +
  "This attempt did not create a branch or pull request.";

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
      await screen.findByRole("button", { name: "Create documentation PR" }),
    );

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Could not complete the request");
    expect(alert).toHaveTextContent("cannot publish there");
    expect(alert).toHaveTextContent("matt/pi");
    expect(alert).toHaveTextContent("Contents: read/write");
    expect(alert).toHaveTextContent("Pull requests: read/write");
    expect(screen.getByText("Publication needs attention")).toBeInTheDocument();
    expect(
      screen.getByText(
        "Follow the guidance above, refresh the preview, and try again.",
      ),
    ).toBeInTheDocument();
  });
});
