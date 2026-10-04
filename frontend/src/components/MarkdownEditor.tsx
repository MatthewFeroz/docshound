import { useEffect, useRef, useState } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type EasyMDE from "easymde";
import "easymde/dist/easymde.min.css";

export function MarkdownEditor({
  value,
  onChange,
}: {
  value: string;
  onChange: (value: string) => void;
}) {
  const textarea = useRef<HTMLTextAreaElement>(null);
  const instance = useRef<EasyMDE | null>(null);
  const change = useRef(onChange);
  const current = useRef(value);
  const [feedback, setFeedback] = useState("");
  change.current = onChange;
  current.current = value;
  useEffect(() => {
    let disposed = false;
    void import("easymde")
      .then(({ default: Editor }) => {
        if (disposed || !textarea.current) return;
        const button = (
          name: string,
          text: string,
          title: string,
          action: (editor: EasyMDE) => void,
          noDisable = false,
        ) => ({
          name,
          text,
          title,
          action,
          noDisable,
          className: "editor-text-button",
        });
        const editor = new Editor({
          element: textarea.current,
          initialValue: current.current,
          autoDownloadFontAwesome: false,
          spellChecker: false,
          nativeSpellcheck: true,
          inputStyle: "contenteditable",
          forceSync: true,
          maxHeight: "520px",
          sideBySideFullscreen: false,
          status: ["words", "lines"],
          previewRender: (source) =>
            renderToStaticMarkup(
              <ReactMarkdown remarkPlugins={[remarkGfm]}>
                {source}
              </ReactMarkdown>,
            ),
          toolbar: [
            button("bold", "B", "Bold", Editor.toggleBold),
            button("italic", "I", "Italic", Editor.toggleItalic),
            button("heading", "H", "Heading", Editor.toggleHeadingSmaller),
            "|",
            button(
              "unordered-list",
              "• List",
              "Bulleted list",
              Editor.toggleUnorderedList,
            ),
            button(
              "ordered-list",
              "1. List",
              "Numbered list",
              Editor.toggleOrderedList,
            ),
            button("link", "Link", "Insert link", Editor.drawLink),
            button("code", "</>", "Code block", Editor.toggleCodeBlock),
            button("table", "Table", "Insert table", Editor.drawTable),
            "|",
            button("undo", "↶", "Undo", Editor.undo),
            button("redo", "↷", "Redo", Editor.redo),
            "|",
            button("preview", "Preview", "Preview", Editor.togglePreview, true),
            button(
              "side-by-side",
              "Split view",
              "Split view",
              Editor.toggleSideBySide,
              true,
            ),
            button(
              "fullscreen",
              "Fullscreen",
              "Fullscreen",
              Editor.toggleFullScreen,
              true,
            ),
            button(
              "copy",
              "Copy",
              "Copy Markdown",
              async (editor) => {
                try {
                  await navigator.clipboard.writeText(editor.value());
                  setFeedback("Markdown copied.");
                } catch {
                  editor.codemirror.focus();
                  editor.codemirror.execCommand("selectAll");
                  setFeedback(
                    "Markdown selected. Use your keyboard's copy shortcut.",
                  );
                }
              },
              true,
            ),
          ],
        });
        instance.current = editor;
        editor.codemirror.on("change", () => change.current(editor.value()));
        const input = editor.codemirror.getInputField();
        input.setAttribute("aria-label", "Edit Markdown");
        input.setAttribute("role", "textbox");
        input.setAttribute("aria-multiline", "true");
        textarea.current.parentElement
          ?.querySelectorAll<HTMLButtonElement>(".editor-toolbar button")
          .forEach((item) => {
            item.tabIndex = 0;
          });
      })
      .catch(() =>
        setFeedback(
          "The formatting toolbar could not load. You can still edit the Markdown below.",
        ),
      );
    return () => {
      disposed = true;
      instance.current?.toTextArea();
      instance.current = null;
    };
  }, []);
  useEffect(() => {
    if (instance.current && instance.current.value() !== value)
      instance.current.value(value);
  }, [value]);
  return (
    <div className="rich-markdown-editor">
      <textarea
        id="markdown-editor"
        ref={textarea}
        defaultValue={value}
        aria-label="Edit Markdown"
        onChange={(event) => onChange(event.target.value)}
      />
      <p role="status">{feedback}</p>
    </div>
  );
}
