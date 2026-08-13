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
  eventHandler: undefined as ((event: unknown) => void) | undefined,
}));

vi.mock("../api", () => ({
  api: {
    createRun: mocks.createRun,
    getRuntimeConfig: mocks.getRuntimeConfig,
    getRun: mocks.getRun,
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
  issues_scraped: 0,
  pull_requests_scraped: 0,
  clusters_found: 0,
  docs_sources: [],
  top_gaps: [],
  decisions: [],
  errors: [],
};

const progressiveGap: GapCluster = {
  name: "Retry behavior",
  summary: "Retry behavior needs documentation.",
  recurring_question: "How do retries work?",
  issue_numbers: [12],
  pr_numbers: [],
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

describe("HomePage live analysis", () => {
  beforeEach(() => {
    mocks.eventHandler = undefined;
    mocks.createRun.mockReset();
    mocks.getRuntimeConfig.mockReset();
    mocks.getRun.mockReset();
    mocks.getRuntimeConfig.mockResolvedValue({
      write_enabled: false,
      llm_gateway: "merge",
      llm_primary_model: "google/gemini-3.7-flash",
      llm_fallback_model: "openai/gpt-5.6-luna",
    });
    mocks.createRun.mockResolvedValue({
      run_id: runningRun.run_id,
      status: "running",
      repo: runningRun.repo,
    });
    mocks.getRun.mockResolvedValue(runningRun);
  });

  it("renders a gap as soon as it arrives on the event stream", async () => {
    render(
      <MemoryRouter>
        <HomePage />
      </MemoryRouter>,
    );

    fireEvent.change(screen.getByPlaceholderText(/paste your repo/i), {
      target: { value: "acme/product" },
    });
    fireEvent.click(screen.getByRole("button", { name: /run agent/i }));

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
});
