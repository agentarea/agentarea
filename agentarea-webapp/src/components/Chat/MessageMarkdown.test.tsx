import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { MessageMarkdown } from "./MessageMarkdown";

function render(content: string, isStreaming = false) {
  return renderToStaticMarkup(
    <MessageMarkdown content={content} isStreaming={isStreaming} />
  );
}

describe("MessageMarkdown", () => {
  it("repairs incomplete Markdown only while content is streaming", () => {
    const content = "Before **unfinished";
    const streaming = render(content, true);
    const completed = render(content);

    expect(streaming).toContain('data-streamdown="strong"');
    expect(streaming).toContain("unfinished</span>");
    expect(completed).toContain("Before **unfinished");
    expect(completed).not.toContain('data-streamdown="strong"');
  });

  it("renders rich completed content through the real static renderer", () => {
    const markup = render(`# Result

- first
- second

1. ordered

> quoted evidence

| Name | Value |
| --- | --- |
| Alpha | 42 |

Use \`inlineValue\`.

\`\`\`ts
const answer = 42;
\`\`\``);

    expect(markup).toContain('data-streamdown="heading-1"');
    expect(markup).toContain('data-streamdown="unordered-list"');
    expect(markup).toContain('data-streamdown="ordered-list"');
    expect(markup).toContain('data-streamdown="blockquote"');
    expect(markup).toContain('data-streamdown="table"');
    expect(markup).toContain('data-streamdown="code-block"');
    expect(markup).toContain('data-streamdown="code-block-copy-button"');
    expect(markup).toContain("quoted evidence");
    expect(markup).toContain("const answer = 42;");
    expect(markup).toContain("inlineValue");
    expect(markup).not.toContain('node="[object Object]"');
  });

  it("keeps reachable file links clickable and sandbox files as honest chips", () => {
    const markup = render(
      "[report.csv](https://example.com/report.csv) [notes.md](/api/files/notes.md) [private.pdf](sandbox:/private.pdf)"
    );

    expect(markup).toContain('href="https://example.com/report.csv"');
    expect(markup).toContain('href="/api/files/notes.md"');
    expect(markup).toContain("private.pdf");
    expect(markup).not.toContain("sandbox:/private.pdf");
  });

  it("does not emit unsafe link targets", () => {
    const markup = render("Keep [this label](javascript:alert(1)) visible.");

    expect(markup).toContain("this label");
    expect(markup).not.toContain("javascript:");
  });
});
