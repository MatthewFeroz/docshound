import { act, render, screen, waitFor } from "@testing-library/react";

import { MarkdownEditor } from "./MarkdownEditor";

const mocks = vi.hoisted(() => ({
  focus: vi.fn(),
  execCommand: vi.fn(),
  toolbar: [] as Array<{
    name?: string;
    action?: (editor: unknown) => void | Promise<void>;
  }>,
  editor: null as unknown,
}));

vi.mock("easymde", () => ({
  default: class {
    static toggleBold = vi.fn();
    static toggleItalic = vi.fn();
    static toggleHeadingSmaller = vi.fn();
    static toggleUnorderedList = vi.fn();
    static toggleOrderedList = vi.fn();
    static drawLink = vi.fn();
    static toggleCodeBlock = vi.fn();
    static drawTable = vi.fn();
    static undo = vi.fn();
    static redo = vi.fn();
    static togglePreview = vi.fn();
    static toggleSideBySide = vi.fn();
    static toggleFullScreen = vi.fn();
    codemirror: {
      on: ReturnType<typeof vi.fn>;
      getInputField: () => HTMLTextAreaElement;
      focus: typeof mocks.focus;
      execCommand: typeof mocks.execCommand;
    };
    value = () => "# Current edited Markdown";
    toTextArea = vi.fn();
    constructor(options: {
      element: HTMLTextAreaElement;
      toolbar: typeof mocks.toolbar;
    }) {
      mocks.toolbar = options.toolbar;
      mocks.editor = this;
      this.codemirror = {
        on: vi.fn(),
        getInputField: () => options.element,
        focus: mocks.focus,
        execCommand: mocks.execCommand,
      };
    }
  },
}));

async function copyMarkdown() {
  render(<MarkdownEditor value="# Original" onChange={vi.fn()} />);
  await waitFor(() => expect(mocks.editor).not.toBeNull());
  const copy = mocks.toolbar.find((item) => item.name === "copy")!;
  await act(async () => copy.action!(mocks.editor));
}

describe("MarkdownEditor copy", () => {
  beforeEach(() => {
    mocks.editor = null;
    mocks.focus.mockClear();
    mocks.execCommand.mockClear();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("selects the current Markdown when the Clipboard API is unavailable", async () => {
    vi.stubGlobal("navigator", { clipboard: undefined });
    await copyMarkdown();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Markdown selected. Use your keyboard's copy shortcut.",
    );
    expect(mocks.focus).toHaveBeenCalledOnce();
    expect(mocks.execCommand).toHaveBeenCalledWith("selectAll");
  });

  it("offers keyboard copying when clipboard permissions reject", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("Permission denied"));
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    await copyMarkdown();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Markdown selected. Use your keyboard's copy shortcut.",
    );
    expect(writeText).toHaveBeenCalledWith("# Current edited Markdown");
    expect(mocks.execCommand).toHaveBeenCalledWith("selectAll");
  });

  it("copies the current editor value when clipboard access succeeds", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    vi.stubGlobal("navigator", { clipboard: { writeText } });
    await copyMarkdown();
    expect(screen.getByRole("status")).toHaveTextContent("Markdown copied.");
    expect(writeText).toHaveBeenCalledWith("# Current edited Markdown");
    expect(mocks.execCommand).not.toHaveBeenCalled();
  });
});
