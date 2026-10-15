import { describe, expect, it } from "vitest";
import {
  markdownBeyondSummary,
  markdownExceedsPreview,
  markdownSummary,
  markdownToPlainText,
} from "./markdown-plain-text";

describe("markdownToPlainText", () => {
  it("drops emphasis and code markers but keeps the words", () => {
    expect(
      markdownToPlainText("**Permanently** delete a `repo`. _Cannot_ be ~~un~~done.")
    ).toBe("Permanently delete a repo. Cannot be undone.");
  });

  it("flattens paragraphs into one line, keeping list items apart", () => {
    expect(
      markdownToPlainText(
        "Open a new issue.\n\n- `title` is required\n- `labels` are optional\n1. first"
      )
    ).toBe("Open a new issue. · title is required · labels are optional · first");
  });

  it("keeps link labels and drops images, headings and HTML", () => {
    expect(
      markdownToPlainText(
        "## Search\n> See [the docs](https://x.dev) ![logo](a.png) <br/>now"
      )
    ).toBe("Search See the docs now");
  });

  it("does not open with a dot when the text starts with a list", () => {
    expect(markdownToPlainText("- one\n- two")).toBe("one · two");
  });

  it("keeps the code of a fenced block and leaves snake_case names alone", () => {
    expect(markdownToPlainText("Run:\n```bash\nlist_repos --all\n```")).toBe(
      "Run: list_repos --all"
    );
  });
});

describe("markdownSummary", () => {
  it("keeps the first paragraph and drops what follows", () => {
    expect(
      markdownSummary("Open a new issue.\n\n- `title` is required\n- `labels` are optional")
    ).toBe("Open a new issue.");
  });

  it("stops at a list that starts right under the first line", () => {
    expect(markdownSummary("Open a new issue:\n- title\n- body")).toBe(
      "Open a new issue:"
    );
  });

  it("joins a paragraph wrapped over several lines and drops its markup", () => {
    expect(markdownSummary("**Permanently** delete\na repository.")).toBe(
      "Permanently delete a repository."
    );
  });
});

describe("markdownBeyondSummary", () => {
  it("returns only what follows the first paragraph", () => {
    expect(
      markdownBeyondSummary("Open a new issue.\n\n- `title` is required\n- `labels` are optional")
    ).toBe("- `title` is required\n- `labels` are optional");
  });

  it("returns nothing when the summary is the whole text", () => {
    expect(markdownBeyondSummary("Read a file.")).toBe("");
  });

  it("returns the whole text when the first paragraph is too long for the cell", () => {
    const long = "word ".repeat(40).trim();
    expect(markdownBeyondSummary(`${long}\n\n- more`)).toBe(`${long}\n\n- more`);
  });
});

describe("markdownExceedsPreview", () => {
  it("is false when the whole text is its first sentence", () => {
    expect(markdownExceedsPreview("Read a file's contents at a ref.")).toBe(false);
  });

  it("is false when the only difference is formatting", () => {
    expect(markdownExceedsPreview("**Permanently** delete a `repo`.")).toBe(false);
  });

  it("is true when more follows the first paragraph", () => {
    expect(
      markdownExceedsPreview("Open a new issue.\n\n- `title` is required")
    ).toBe(true);
  });

  it("is true when the first paragraph runs past the preview length", () => {
    expect(markdownExceedsPreview("word ".repeat(40))).toBe(true);
    expect(markdownExceedsPreview("short", 3)).toBe(true);
  });
});
