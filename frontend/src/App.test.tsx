import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import App from "./App";
import { api } from "./api";

describe("DocsHound frontend", () => {
  afterEach(() => vi.restoreAllMocks());
  it("renders the independent frontend landing page", () => {
    render(
      <MemoryRouter initialEntries={["/"]}>
        <App />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("heading", { name: /into citeable documentation/i }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /run agent/i }),
    ).toBeInTheDocument();
  });

  it("redirects the former showcase route to the consolidated homepage", async () => {
    render(
      <MemoryRouter initialEntries={["/showcase"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      await screen.findByRole("heading", {
        name: /see the evidence, the decisions, and the draft/i,
      }),
    ).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /github/i })).toBeInTheDocument();
  });

  it("loads a review page opened directly by its route", async () => {
    vi.spyOn(api, "listFindings").mockResolvedValue([]);
    render(
      <MemoryRouter initialEntries={["/findings"]}>
        <App />
      </MemoryRouter>,
    );

    expect(screen.getByText("Loading page…")).toBeInTheDocument();
    expect(
      await screen.findByRole("heading", {
        name: /turn repository activity into useful documentation/i,
      }),
    ).toBeInTheDocument();
    expect(api.listFindings).toHaveBeenCalledOnce();
  });
});
