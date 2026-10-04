import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { Link, MemoryRouter, Route, Routes } from "react-router-dom";

import type { DocumentPayload, Finding } from "../types";
import { DocumentPage } from "./DocumentPage";
import { FindingPage } from "./FindingPage";

const apiMocks = vi.hoisted(() => ({
  approveFinding: vi.fn(),
  getDocument: vi.fn(),
  getFinding: vi.fn(),
  rejectFinding: vi.fn(),
}));

vi.mock("../api", () => ({
  api: apiMocks,
  assetUrl: (path: string) => path,
}));

vi.mock("../components/MarkdownEditor", () => ({
  MarkdownEditor: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (value: string) => void;
  }) => (
    <textarea
      aria-label="Edit Markdown"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
}));

const finding: Finding = {
  run_id: "review-run",
  repo: "example/sdk",
  index: 0,
  cluster: {
    name: "Client setup",
    summary: "Explain client setup.",
    recurring_question: "How do I configure the client?",
    issue_numbers: [],
    pr_numbers: [],
    issue_refs: [],
    pr_refs: [],
    finding_type: "open_gap",
    severity: "high",
    confidence: 0.9,
    draft_title: "Client setup",
    draft_summary: "Explain client setup.",
    draft_markdown: "# Original agent draft",
    review_status: "approved",
    approved_document_slug: "client-setup",
    documentation_coverage: null,
  },
  source_issues: [],
  source_pull_requests: [],
  approved_document: {
    slug: "client-setup",
    run_id: "review-run",
    gap_index: 0,
    repo: "example/sdk",
    title: "Client setup",
    summary: "Explain client setup.",
    markdown: "# Saved reviewer revision\n\nKeep the retry policy.",
    source_issues: [],
    approved_at: "2026-10-04T00:00:00Z",
    updated_at: "2026-10-04T00:00:00Z",
  },
  documentation_change: null,
};

const payload: DocumentPayload = {
  document: finding.approved_document!,
  body_markdown: finding.approved_document!.markdown,
  documentation_change: null,
  suggested_file_path: null,
  suggested_action: null,
  suggested_target_repo: null,
  write_enabled: false,
};

function renderPage(path = "/runs/review-run/findings/0") {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Link to="/runs/next-run/findings/0">Next finding</Link>
      <Routes>
        <Route path="/runs/:runId/findings/:index" element={<FindingPage />} />
        <Route path="/documents/:slug" element={<DocumentPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe("FindingPage review navigation", () => {
  let scrollIntoView: ReturnType<typeof vi.fn>;
  const originalScroll = Object.getOwnPropertyDescriptor(
    HTMLElement.prototype,
    "scrollIntoView",
  );

  beforeEach(() => {
    apiMocks.getFinding.mockResolvedValue(finding);
    apiMocks.getDocument.mockResolvedValue(payload);
    apiMocks.approveFinding.mockResolvedValue(payload);
    scrollIntoView = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
      configurable: true,
      value: scrollIntoView,
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.resetAllMocks();
    if (originalScroll)
      Object.defineProperty(
        HTMLElement.prototype,
        "scrollIntoView",
        originalScroll,
      );
    else Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
  });

  it("opens and focuses the editor from the approved document link", async () => {
    renderPage("/documents/client-setup");

    fireEvent.click(await screen.findByRole("link", { name: "Edit Markdown" }));

    const editor = await screen.findByRole("region", {
      name: "Human review draft",
    });
    expect(editor).toHaveAttribute("id", "draft-editor");
    expect(editor).toHaveFocus();
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "start" });
    expect(screen.getByRole("textbox", { name: "Edit Markdown" })).toHaveValue(
      finding.approved_document!.markdown,
    );

    fireEvent.click(screen.getByRole("button", { name: "Update and open" }));
    await waitFor(() => {
      expect(apiMocks.approveFinding).toHaveBeenCalledWith(
        "review-run",
        0,
        finding.approved_document!.markdown,
      );
    });
    expect(
      await screen.findByRole("button", { name: "Copy Markdown" }),
    ).toBeInTheDocument();
  });

  it("keeps ordinary finding navigation at the evidence", async () => {
    renderPage();

    await screen.findByRole("textbox", { name: "Edit Markdown" });
    expect(scrollIntoView).not.toHaveBeenCalled();
  });

  it("uses the agent draft until a reviewer approves a revision", async () => {
    apiMocks.getFinding.mockResolvedValue({
      ...finding,
      approved_document: null,
    });
    renderPage();

    expect(
      await screen.findByRole("textbox", { name: "Edit Markdown" }),
    ).toHaveValue(finding.cluster.draft_markdown);
  });

  it.each(["resolve", "reject"])(
    "ignores a previous finding request that later %ss",
    async (result) => {
      let resolve!: (value: Finding) => void;
      let reject!: (error: Error) => void;
      const previousRequest = new Promise<Finding>((onResolve, onReject) => {
        resolve = onResolve;
        reject = onReject;
      });
      apiMocks.getFinding.mockReturnValueOnce(previousRequest);
      apiMocks.getFinding.mockResolvedValueOnce({
        ...finding,
        run_id: "next-run",
        approved_document: null,
        cluster: {
          ...finding.cluster,
          name: "Next finding title",
          draft_markdown: "# Next draft",
        },
      });
      renderPage();

      fireEvent.click(screen.getByRole("link", { name: "Next finding" }));
      const editor = await screen.findByRole("textbox", {
        name: "Edit Markdown",
      });
      fireEvent.change(editor, {
        target: { value: "# Unsaved reviewer edit" },
      });

      await act(async () => {
        if (result === "resolve") resolve(finding);
        else reject(new Error("Previous finding failed to load"));
      });

      expect(editor).toHaveValue("# Unsaved reviewer edit");
      expect(
        screen.getByRole("heading", { name: "Next finding title" }),
      ).toBeInTheDocument();
      expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    },
  );
});
