import { fireEvent, render, screen, within } from "@testing-library/react";
import {
  MemoryRouter,
  Route,
  Routes,
  useLocation,
  useNavigate,
} from "react-router-dom";

import type { Finding, ReviewStatus } from "../types";
import { FindingsPage } from "./FindingsPage";

const apiMocks = vi.hoisted(() => ({ listFindings: vi.fn() }));
vi.mock("../api", () => ({ api: apiMocks }));

function makeFinding(
  name: string,
  index: number,
  reviewStatus: ReviewStatus = "pending_review",
  changeStatus: string | null = null,
): Finding {
  return {
    run_id: "triage-run",
    repo: index === 1 ? "example/gateway" : "example/sdk",
    index,
    cluster: {
      name,
      summary: "Document the retry policy.",
      recurring_question: "How do I configure this?",
      issue_numbers: [42],
      pr_numbers: [],
      issue_refs: [],
      pr_refs: [],
      finding_type: "open_gap",
      severity: "high",
      confidence: 0.9,
      draft_title: name,
      draft_summary: "Configuration guidance.",
      draft_markdown: `# ${name}`,
      review_status: reviewStatus,
      approved_document_slug:
        reviewStatus === "approved" ? "approved-doc" : null,
      documentation_coverage: null,
    },
    source_issues: [],
    source_pull_requests: [],
    approved_document: null,
    documentation_change: changeStatus
      ? {
          document_slug: "approved-doc",
          target_repo: "example/sdk",
          publish_repo: null,
          base_branch: "main",
          branch_name: "docshound/configuration",
          file_path: "docs/configuration.md",
          file_format: "markdown",
          detected_by: "manual path",
          edit_action: "create_page",
          content: `# ${name}`,
          patch: `+# ${name}`,
          existing_sha: null,
          status: changeStatus,
          pr_number: null,
          pr_url: null,
          error: null,
          created_at: "2026-10-04T00:00:00Z",
          updated_at: "2026-10-04T00:00:00Z",
        }
      : null,
  };
}

const findings = [
  makeFinding("SDK configuration", 0),
  makeFinding("Gateway deployment", 1),
  makeFinding("Approved retry guide", 2, "approved"),
  makeFinding("Existing coverage", 3, "no_change_needed"),
  makeFinding("Awaiting GitHub confirmation", 4, "approved", "branch_ready"),
  makeFinding("Publication error", 5, "approved", "failed"),
  makeFinding("Prepared patch", 6, "approved", "preview_ready"),
  makeFinding("Opened documentation PR", 7, "approved", "created"),
  makeFinding("Rejected proposal", 8, "rejected"),
];

function Location() {
  return <span aria-label="Current URL">{useLocation().search}</span>;
}

function FindingDetail() {
  const navigate = useNavigate();
  return <button onClick={() => navigate(-1)}>Back to findings</button>;
}

function renderPage(path = "/findings") {
  render(
    <MemoryRouter initialEntries={[path]}>
      <Location />
      <Routes>
        <Route path="/findings" element={<FindingsPage />} />
        <Route
          path="/runs/:runId/findings/:index"
          element={<FindingDetail />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

describe("FindingsPage triage", () => {
  beforeEach(() => {
    apiMocks.listFindings.mockResolvedValue(findings);
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it("distinguishes review, coverage, and publication states on each card", async () => {
    renderPage();
    await screen.findByRole("heading", { name: "SDK configuration" });

    for (const [name, status] of [
      ["SDK configuration", "Ready to review"],
      ["Approved retry guide", "Approved"],
      ["Existing coverage", "No change needed"],
      ["Awaiting GitHub confirmation", "Confirm on GitHub"],
      ["Publication error", "Publication failed"],
      ["Prepared patch", "Patch ready"],
      ["Opened documentation PR", "PR created"],
      ["Rejected proposal", "Rejected"],
    ]) {
      const card = screen.getByRole("heading", { name }).closest("article")!;
      expect(within(card).getByText(status)).toBeInTheDocument();
    }
  });

  it("combines case-insensitive search terms with a review-status filter", async () => {
    renderPage();
    const search = await screen.findByRole("searchbox", {
      name: "Search findings",
    });
    fireEvent.change(search, { target: { value: "  SDK RETRY  " } });
    fireEvent.change(screen.getByRole("combobox", { name: "Review status" }), {
      target: { value: "pending_review" },
    });

    expect(screen.getByRole("status")).toHaveTextContent(
      "Showing 1 of 9 findings",
    );
    expect(
      screen.getByRole("heading", { name: "SDK configuration" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "Gateway deployment" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("Current URL")).toHaveTextContent(
      "status=pending_review",
    );
  });

  it("preserves filtered URLs when opening a finding and returning", async () => {
    renderPage("/findings?q=example%2Fsdk&status=branch_ready");
    fireEvent.click(await screen.findByRole("link", { name: "View finding" }));
    fireEvent.click(screen.getByRole("button", { name: "Back to findings" }));

    expect(
      await screen.findByRole("searchbox", { name: "Search findings" }),
    ).toHaveValue("example/sdk");
    expect(screen.getByRole("combobox", { name: "Review status" })).toHaveValue(
      "branch_ready",
    );
    expect(screen.getByRole("status")).toHaveTextContent(
      "Showing 1 of 9 findings",
    );
  });

  it("offers recovery for an empty match without claiming there are no findings", async () => {
    renderPage("/findings?q=unmatched&status=failed&keep=preserved");
    expect(
      await screen.findByRole("heading", {
        name: "No findings match these filters.",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { name: "No findings yet." }),
    ).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Show all findings" }));
    expect(screen.getByRole("status")).toHaveTextContent(
      "Showing 9 of 9 findings",
    );
    expect(screen.getByLabelText("Current URL")).toHaveTextContent(
      "?keep=preserved",
    );
    expect(screen.queryByRole("button", { name: "Clear filters" })).toBeNull();
  });

  it("treats unknown status values as all statuses", async () => {
    renderPage("/findings?status=constructor");
    expect(
      await screen.findByRole("combobox", { name: "Review status" }),
    ).toHaveValue("");
    expect(screen.getByRole("status")).toHaveTextContent(
      "Showing 9 of 9 findings",
    );
  });

  it("retains the initial empty-state action when there are no saved findings", async () => {
    apiMocks.listFindings.mockResolvedValue([]);
    renderPage();
    expect(
      await screen.findByRole("heading", { name: "No findings yet." }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("searchbox")).toBeNull();
  });

  it("shows a rejection even when an older approved document remains", async () => {
    apiMocks.listFindings.mockResolvedValue([
      {
        ...makeFinding("Rejected revision", 0, "rejected"),
        cluster: {
          ...makeFinding("Rejected revision", 0, "rejected").cluster,
          approved_document_slug: "previously-approved",
        },
      },
    ]);
    renderPage();
    const heading = await screen.findByRole("heading", {
      name: "Rejected revision",
    });
    expect(
      within(heading.closest("article")!).getByText("Rejected"),
    ).toBeInTheDocument();
  });

  it("shows a rejection even when an earlier patch was prepared", async () => {
    apiMocks.listFindings.mockResolvedValue([
      makeFinding("Rejected after patch", 0, "rejected", "preview_ready"),
    ]);
    renderPage();
    const heading = await screen.findByRole("heading", {
      name: "Rejected after patch",
    });
    expect(
      within(heading.closest("article")!).getByText("Rejected"),
    ).toBeInTheDocument();
  });
});
