import { act, fireEvent, render, screen } from "@testing-library/react";
import {
  Link,
  MemoryRouter,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";

import type { DocumentPayload } from "../types";
import { DocumentPage } from "./DocumentPage";
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

type Page = "document" | "preview";

function payload(slug: string, page: Page): DocumentPayload {
  return {
    document: {
      slug,
      run_id: "review-run",
      gap_index: 0,
      repo: `example/${slug}`,
      title: `${slug} approved document`,
      summary: "Configuration guidance.",
      markdown: `# ${slug} body`,
      source_issues: [],
      approved_at: "2026-10-04T00:00:00Z",
      updated_at: "2026-10-04T00:00:00Z",
    },
    body_markdown: `# ${slug} body`,
    documentation_change:
      page === "preview"
        ? {
            document_slug: slug,
            target_repo: `example/${slug}`,
            publish_repo: null,
            base_branch: "main",
            branch_name: `docshound/${slug}`,
            file_path: `docs/${slug}.md`,
            file_format: "markdown",
            detected_by: "manual path",
            edit_action: "create_page",
            content: `# ${slug} body`,
            patch: `+# ${slug} body`,
            existing_sha: null,
            status: "preview_ready",
            pr_number: null,
            pr_url: null,
            error: null,
            created_at: "2026-10-04T00:00:00Z",
            updated_at: "2026-10-04T00:00:00Z",
          }
        : null,
    suggested_file_path: `docs/${slug}.md`,
    suggested_action: "create_page",
    suggested_target_repo: `example/${slug}`,
    write_enabled: true,
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((onResolve, onReject) => {
    resolve = onResolve;
    reject = onReject;
  });
  return { promise, resolve, reject };
}

function Location() {
  return <span aria-label="Current route">{useLocation().pathname}</span>;
}

function renderPage(page: Page) {
  const suffix = page === "preview" ? "/pull-request" : "";
  render(
    <MemoryRouter initialEntries={[`/documents/first${suffix}`]}>
      <Location />
      <Link to={`/documents/second${suffix}`}>Next document</Link>
      <Routes>
        <Route path="/documents/:slug" element={<DocumentPage />} />
        <Route
          path="/documents/:slug/pull-request"
          element={<PullRequestPage />}
        />
      </Routes>
    </MemoryRouter>,
  );
}

function pageAction(page: Page) {
  return page === "document"
    ? "Prepare documentation PR"
    : "Publish upstream PR";
}

describe.each<Page>(["document", "preview"])("%s route safety", (page) => {
  beforeEach(() => {
    apiMocks.getDocument.mockImplementation((slug: string) =>
      Promise.resolve(payload(slug, page)),
    );
    apiMocks.previewPullRequest.mockImplementation((slug: string) =>
      Promise.resolve(payload(slug, "preview")),
    );
    apiMocks.createPullRequest.mockImplementation((slug: string) =>
      Promise.resolve(payload(slug, "preview")),
    );
  });

  afterEach(() => {
    vi.resetAllMocks();
  });

  it("removes the previous document's actions while the next document loads", async () => {
    const next = deferred<DocumentPayload>();
    apiMocks.getDocument.mockImplementation((slug: string) =>
      slug === "second" ? next.promise : Promise.resolve(payload(slug, page)),
    );
    renderPage(page);
    await screen.findByRole("button", { name: pageAction(page) });

    fireEvent.click(screen.getByRole("link", { name: "Next document" }));
    expect(screen.queryByRole("button", { name: pageAction(page) })).toBeNull();
    expect(screen.queryByRole("button", { name: "Copy Markdown" })).toBeNull();
    expect(screen.queryByText("first approved document")).toBeNull();
    expect(screen.queryByText("+# first body")).toBeNull();

    await act(async () => next.resolve(payload("second", page)));
    expect(
      screen.getByRole("textbox", {
        name: "Upstream documentation repository",
      }),
    ).toHaveValue("example/second");
    fireEvent.click(screen.getByRole("button", { name: pageAction(page) }));
    if (page === "document")
      expect(apiMocks.previewPullRequest).toHaveBeenCalledWith(
        "second",
        "example/second",
        "docs/second.md",
      );
    else expect(apiMocks.createPullRequest).toHaveBeenCalledWith("second");
  });

  it.each(["resolve", "reject"])(
    "ignores an old document request that later %ss",
    async (result) => {
      const old = deferred<DocumentPayload>();
      apiMocks.getDocument.mockReturnValueOnce(old.promise);
      apiMocks.getDocument.mockResolvedValueOnce(payload("second", page));
      renderPage(page);
      fireEvent.click(screen.getByRole("link", { name: "Next document" }));
      await screen.findByRole("button", { name: pageAction(page) });

      const repository = screen.getByRole("textbox", {
        name: "Upstream documentation repository",
      });
      fireEvent.change(repository, { target: { value: "reviewer/current" } });
      await act(async () => {
        if (result === "resolve") old.resolve(payload("first", page));
        else old.reject(new Error("Old document failed"));
      });

      expect(repository).toHaveValue("reviewer/current");
      expect(screen.queryByRole("alert")).toBeNull();
      expect(screen.queryByText("first approved document")).toBeNull();
      expect(screen.queryByText("+# first body")).toBeNull();
    },
  );

  it("clears a previous load error when the document route changes", async () => {
    apiMocks.getDocument.mockRejectedValueOnce(new Error("First load failed"));
    renderPage(page);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      "First load failed",
    );

    fireEvent.click(screen.getByRole("link", { name: "Next document" }));
    await screen.findByRole("button", { name: pageAction(page) });
    expect(screen.queryByRole("alert")).toBeNull();
  });
});

describe("pending document operations", () => {
  afterEach(() => {
    vi.resetAllMocks();
  });

  it("does not redirect the current document when a previous preview completes", async () => {
    const oldPreview = deferred<DocumentPayload>();
    apiMocks.getDocument.mockImplementation((slug: string) =>
      Promise.resolve(payload(slug, "document")),
    );
    apiMocks.previewPullRequest.mockReturnValueOnce(oldPreview.promise);
    renderPage("document");
    fireEvent.click(
      await screen.findByRole("button", { name: "Prepare documentation PR" }),
    );
    fireEvent.click(screen.getByRole("link", { name: "Next document" }));
    await screen.findByRole("heading", { name: "second approved document" });

    await act(async () => oldPreview.resolve(payload("first", "preview")));
    expect(screen.getByLabelText("Current route")).toHaveTextContent(
      "/documents/second",
    );
    expect(screen.queryByText("Review the repository change")).toBeNull();
  });

  it.each(["refresh", "publish"])(
    "ignores a previous %s operation after changing previews",
    async (operation) => {
      const oldOperation = deferred<DocumentPayload>();
      apiMocks.getDocument.mockImplementation((slug: string) =>
        Promise.resolve(payload(slug, "preview")),
      );
      apiMocks.previewPullRequest.mockReturnValueOnce(oldOperation.promise);
      apiMocks.createPullRequest.mockReturnValueOnce(oldOperation.promise);
      renderPage("preview");
      await screen.findByRole("button", { name: "Publish upstream PR" });
      fireEvent.click(
        screen.getByRole("button", {
          name:
            operation === "refresh" ? "Refresh preview" : "Publish upstream PR",
        }),
      );
      fireEvent.click(screen.getByRole("link", { name: "Next document" }));
      await screen.findByText("+# second body");

      await act(async () => oldOperation.resolve(payload("first", "preview")));
      expect(screen.getByText("+# second body")).toBeInTheDocument();
      expect(screen.queryByText("+# first body")).toBeNull();
      expect(
        screen.getByRole("button", { name: "Publish upstream PR" }),
      ).toBeEnabled();
    },
  );
});
