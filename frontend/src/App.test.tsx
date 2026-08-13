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

  it("renders the DocsHound product showcase", () => {
    render(
      <MemoryRouter initialEntries={["/showcase"]}>
        <App />
      </MemoryRouter>,
    );

    expect(
      screen.getByRole("heading", {
        name: /documentation that keeps up with what you ship/i,
      }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("heading", { name: /a stateful loop/i }),
    ).toBeInTheDocument();
  });
});
