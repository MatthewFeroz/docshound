import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";

import App from "./App";

vi.mock("./pages/FindingsPage", () => {
  throw new TypeError("Failed to fetch dynamically imported module");
});

describe("page loading", () => {
  it("explains a page that could not be loaded instead of rendering nothing", async () => {
    vi.spyOn(console, "error").mockImplementation(() => {});
    render(
      <MemoryRouter initialEntries={["/findings"]}>
        <App />
      </MemoryRouter>,
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      "This page could not be loaded. Reload the page to try again.",
    );
  });
});
