import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import App from "./App";

describe("DocsHound frontend", () => {
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
});
