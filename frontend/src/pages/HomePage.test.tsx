import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import type { GapCluster, Run, RunEvent } from "../types";
import { HomePage } from "./HomePage";

const mocks = vi.hoisted(() => ({
  createRun: vi.fn(),
  getRuntimeConfig: vi.fn(),
  getRun: vi.fn(),
  resolveSources: vi.fn(),
  setGitHubApiKey: vi.fn(),
  setMergeGatewayApiKey: vi.fn(),
  eventHandler: undefined as ((event: unknown) => void) | undefined,
}));

vi.mock("../api", () => ({
  api: {
    createRun: mocks.createRun,
    getRuntimeConfig: mocks.getRuntimeConfig,
    getRun: mocks.getRun,
    resolveSources: mocks.resolveSources,
    setGitHubApiKey: mocks.setGitHubApiKey,
    setMergeGatewayApiKey: mocks.setMergeGatewayApiKey,
  },
  subscribeToRun: (_runId: string, onEvent: (event: unknown) => void) => {
    mocks.eventHandler = onEvent;
    return vi.fn();
  },
}));

const runningRun: Run = {
  run_id: "run-12345678",
  status: "running",
  repo: "acme/product",
  dry_run: false,
  documentation_source: {
    kind: "github",
    repo: "acme/product",
    root: "docs",
    url: "https://github.com/acme/product/tree/main/docs",
    confidence: 0.97,
    discovered_by: "readme_docs_link",
    page_count: 24,
  },
  issues_scraped: 0,
  pull_requests_scraped: 0,
  clusters_found: 0,
  docs_sources: [],
  docs_candidates_inspected: 0,
  documentation_issues_scraped: 0,
  documentation_pull_requests_scraped: 0,
  top_gaps: [],
  decisions: [],
  warnings: [],
  errors: [],
};

const progressiveGap: GapCluster = {
  name: "Retry behavior",
  summary: "Retry behavior needs documentation.",
  recurring_question: "How do retries work?",
  issue_numbers: [12],
  pr_numbers: [],
  issue_refs: ["acme/product#12"],
  pr_refs: [],
  finding_type: "open_gap",
  severity: "medium",
  confidence: 0.9,
  draft_title: "Configure retries",
  draft_summary: "Explain bounded retries.",
  draft_markdown: "# Configure retries",
  review_status: "pending_review",
  approved_document_slug: null,
  documentation_coverage: null,
};

async function connectGitHub(container: HTMLElement) {
  await waitFor(() =>
    expect(container.querySelector(".readiness-connect")).toHaveAttribute(
      "data-open",
    ),
  );
  const keyInput = screen.getByLabelText(/fine-grained personal access/i);
  fireEvent.change(keyInput, { target: { value: "github_pat_secret" } });
  fireEvent.click(screen.getByRole("button", { name: /^connect github$/i }));
  await waitFor(() =>
    expect(mocks.setGitHubApiKey).toHaveBeenCalledWith(
      "acme/product",
      "github_pat_secret",
    ),
  );
  await screen.findByText(/deep scan enabled/i);
}

describe("HomePage live analysis", () => {
  beforeEach(() => {
    mocks.eventHandler = undefined;
    mocks.createRun.mockReset();
    mocks.getRuntimeConfig.mockReset();
    mocks.getRun.mockReset();
    mocks.resolveSources.mockReset();
    mocks.setGitHubApiKey.mockReset();
    mocks.setMergeGatewayApiKey.mockReset();
    mocks.getRuntimeConfig.mockResolvedValue({
      write_enabled: false,
      llm_gateway: "merge",
      llm_primary_model: "google/gemini-3.7-flash",
      llm_fallback_model: "openai/gpt-5.6-luna",
      llm_configured: true,
      credential_input_enabled: true,
      github_configured: true,
      github_account: "octocat",
      github_verified_repo: "acme/product",
      github_document_fetch_limit: 100,
      github_documents_per_finding: 8,
    });
    mocks.setMergeGatewayApiKey.mockResolvedValue({
      write_enabled: false,
      llm_gateway: "merge",
      llm_primary_model: "google/gemini-3.7-flash",
      llm_fallback_model: "openai/gpt-5.6-luna",
      llm_configured: true,
      credential_input_enabled: true,
      github_configured: true,
      github_account: "octocat",
      github_verified_repo: "acme/product",
      github_document_fetch_limit: 100,
      github_documents_per_finding: 8,
    });
    mocks.setGitHubApiKey.mockResolvedValue({
      write_enabled: false,
      llm_gateway: "merge",
      llm_primary_model: "google/gemini-3.7-flash",
      llm_fallback_model: "openai/gpt-5.6-luna",
      llm_configured: true,
      credential_input_enabled: true,
      github_configured: true,
      github_account: "octocat",
      github_verified_repo: "acme/product",
      github_document_fetch_limit: 100,
      github_documents_per_finding: 8,
    });
    mocks.createRun.mockResolvedValue({
      run_id: runningRun.run_id,
      status: "running",
      repo: runningRun.repo,
      documentation_source: runningRun.documentation_source,
    });
    mocks.resolveSources.mockResolvedValue({
      product_repo: "acme/product",
      documentation_sources: [runningRun.documentation_source],
      selected_source: runningRun.documentation_source,
      documentation_activity_repos: [],
    });
    mocks.getRun.mockResolvedValue(runningRun);
  });

  it("renders the decorative GitHub workflow panes", () => {
    const { container } = render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    expect(container.querySelector(".hero-floater-left")).toHaveTextContent(
      "12 issues clustered",
    );
    expect(container.querySelector(".hero-floater-right")).toHaveTextContent(
      "Draft → review → approve",
    );
    expect(
      container.querySelector('img[src="/logos/opencode-mark.svg"]'),
    ).toBeInTheDocument();
    expect(
      container.querySelector('img[src="/logos/deepagents-mark.svg"]'),
    ).toBeInTheDocument();
    expect(
      container.querySelector('img[src="/logos/pi-mark.svg"]'),
    ).toBeInTheDocument();
    expect(
      container.querySelector('img[src="/logos/t3-code-mark.svg"]'),
    ).toBeInTheDocument();
    expect(container.querySelectorAll(".source-word")).toHaveLength(4);
  });

  it("sends a Gateway key to the backend without retaining it in the field", async () => {
    const { container } = render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.click(
      container.querySelector("#model-connection .readiness-trigger")!,
    );
    const keyInput = screen.getByLabelText(/merge gateway api key/i);
    fireEvent.change(keyInput, { target: { value: "merge-secret-key" } });
    fireEvent.click(screen.getByRole("button", { name: /save connection/i }));

    await waitFor(() =>
      expect(mocks.setMergeGatewayApiKey).toHaveBeenCalledWith(
        "merge-secret-key",
      ),
    );
    await waitFor(() => expect(keyInput).toHaveValue(""));
    expect(
      screen.getByText(/connected for this local server session/i),
    ).toBeInTheDocument();
  });

  it("verifies a GitHub token before enabling a deep repository run", async () => {
    mocks.getRuntimeConfig.mockResolvedValueOnce({
      write_enabled: false,
      llm_gateway: "merge",
      llm_primary_model: "google/gemini-3.7-flash",
      llm_fallback_model: "openai/gpt-5.6-luna",
      llm_configured: true,
      credential_input_enabled: true,
      github_configured: false,
      github_account: null,
      github_verified_repo: null,
      github_document_fetch_limit: 100,
      github_documents_per_finding: 8,
    });
    const { container } = render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText(/paste your repo/i), {
      target: { value: "https://github.com/acme/product" },
    });
    expect(screen.getByRole("button", { name: /run agent/i })).toBeDisabled();

    await waitFor(() =>
      expect(container.querySelector(".readiness-connect")).toHaveAttribute(
        "data-open",
      ),
    );
    const keyInput = screen.getByLabelText(/fine-grained personal access/i);
    fireEvent.change(keyInput, { target: { value: "github_pat_secret" } });
    fireEvent.click(screen.getByRole("button", { name: /^connect github$/i }));

    await waitFor(() =>
      expect(mocks.setGitHubApiKey).toHaveBeenCalledWith(
        "acme/product",
        "github_pat_secret",
      ),
    );
    await waitFor(() => expect(keyInput).toHaveValue(""));
    expect(await screen.findByText(/deep scan enabled/i)).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.getByRole("button", { name: /run agent/i })).toBeEnabled(),
    );
  });

  it("renders a gap as soon as it arrives on the event stream", async () => {
    const { container } = render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText(/paste your repo/i), {
      target: { value: "acme/product" },
    });
    await connectGitHub(container);
    const runButton = screen.getByRole("button", { name: /run agent/i });
    await waitFor(() => expect(runButton).toBeEnabled());
    fireEvent.click(runButton);

    await waitFor(() =>
      expect(mocks.createRun).toHaveBeenCalledWith(
        "acme/product",
        runningRun.documentation_source,
        true,
      ),
    );

    await waitFor(() => expect(mocks.eventHandler).toBeDefined());
    act(() => {
      mocks.eventHandler?.({
        type: "gap_found",
        index: 0,
        cluster: progressiveGap,
      } satisfies RunEvent);
    });

    expect(await screen.findByText("Retry behavior")).toBeInTheDocument();
    expect(screen.getByText("1 found")).toBeInTheDocument();
  });

  it("shows a separate official docs repo and includes its activity", async () => {
    const externalSource = {
      kind: "github" as const,
      repo: "acme/docs",
      root: "content/en/docs",
      url: "https://docs.acme.dev",
      confidence: 0.99,
      discovered_by: "edit_on_github",
      page_count: 42,
    };
    mocks.resolveSources.mockResolvedValueOnce({
      product_repo: "acme/product",
      documentation_sources: [externalSource],
      selected_source: externalSource,
      documentation_activity_repos: ["acme/docs"],
    });
    const { container } = render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText(/paste your repo/i), {
      target: { value: "acme/product" },
    });
    await connectGitHub(container);

    expect(
      await screen.findAllByText(/acme\/docs \/ content\/en\/docs · 42 pages/i),
    ).not.toHaveLength(0);
    fireEvent.click(
      container.querySelector(".documentation-connect .readiness-trigger")!,
    );
    expect(
      screen.getByText(/also analyze issues and merged prs from acme\/docs/i),
    ).toBeInTheDocument();
    expect(screen.getByRole("checkbox")).toBeChecked();
    expect(screen.getByRole("button", { name: /run agent/i })).toBeEnabled();
  });

  it("keeps one setup section open and shows READY for every completed step", async () => {
    const { container } = render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    const sections = Array.from(
      container.querySelectorAll<HTMLElement>(".readiness-connect"),
    );
    expect(sections).toHaveLength(3);
    expect(
      container.querySelector(".hero-model-picker"),
    ).not.toBeInTheDocument();
    expect(
      container.querySelector(".run-readiness-head"),
    ).not.toBeInTheDocument();
    expect(container.querySelectorAll(".ui-accordion-chevron")).toHaveLength(3);
    await waitFor(() =>
      expect(
        Array.from(
          container.querySelectorAll(".readiness-action"),
          (element) => element.textContent,
        ),
      ).toEqual(["WAITING", "WAITING", "READY"]),
    );
    expect(
      container.querySelector(".github-connect-head"),
    ).not.toBeInTheDocument();

    fireEvent.click(sections[0].querySelector(".readiness-trigger")!);
    await waitFor(() => expect(sections[0]).toHaveAttribute("data-open"));
    fireEvent.click(sections[1].querySelector(".readiness-trigger")!);
    await waitFor(() => {
      expect(sections[0]).not.toHaveAttribute("data-open");
      expect(sections[1]).toHaveAttribute("data-open");
    });
    expect(
      screen.getByText(/connect github to auto-discover the source/i),
    ).toBeInTheDocument();

    fireEvent.change(screen.getByPlaceholderText(/paste your repo/i), {
      target: { value: "acme/product" },
    });
    await waitFor(() => expect(sections[0]).toHaveAttribute("data-open"));
    expect(sections[0].querySelector(".readiness-action")).toHaveTextContent(
      "WAITING",
    );
    expect(mocks.resolveSources).not.toHaveBeenCalled();

    const keyInput = screen.getByLabelText(/fine-grained personal access/i);
    const connectButton = screen.getByRole("button", {
      name: /^connect github$/i,
    });
    expect(keyInput).toBeRequired();
    expect(connectButton).toBeDisabled();
    fireEvent.change(keyInput, { target: { value: "github_pat_secret" } });
    expect(connectButton).toBeEnabled();
    fireEvent.click(connectButton);

    await waitFor(() =>
      expect(mocks.setGitHubApiKey).toHaveBeenCalledWith(
        "acme/product",
        "github_pat_secret",
      ),
    );
    await waitFor(() => expect(mocks.resolveSources).toHaveBeenCalled());
    await waitFor(() => {
      const states = Array.from(
        container.querySelectorAll(".readiness-action"),
        (element) => element.textContent,
      );
      expect(states).toEqual(["READY", "READY", "READY"]);
    });

    fireEvent.click(sections[1].querySelector(".readiness-trigger")!);
    await waitFor(() => expect(sections[1]).toHaveAttribute("data-open"));
    const sourceOptions = container.querySelector(".docs-source-options-row")!;
    expect(sourceOptions).toHaveTextContent(
      "Activity already included for this repository.",
    );
    const sourceChange = screen.getByRole("button", {
      name: /change source/i,
    });
    expect(sourceOptions).toContainElement(sourceChange);
    fireEvent.click(sourceChange);
    expect(
      await screen.findByLabelText(/documentation repository/i),
    ).toBeInTheDocument();
    expect(
      sourceChange.closest("[data-slot='accordion-item']"),
    ).toHaveAttribute("data-open");
  });
});
