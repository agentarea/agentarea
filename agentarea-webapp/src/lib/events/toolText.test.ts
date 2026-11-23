import { describe, expect, it } from "vitest";
import { readableToolText, unwrapSoftBreaks } from "./toolText";

describe("readableToolText", () => {
  it("shows a skill's body without its wrapper and frontmatter", () => {
    const text =
      '<skill_content name="discover">\n---\nname: discover\ndescription: Finds rivals\n---\n# Search\n\nLook wide.\n</skill_content>';
    expect(readableToolText(text)).toBe("# Search\n\nLook wide.");
  });

  it("leaves other output alone", () => {
    expect(readableToolText("---\nplain\n---")).toBe("---\nplain\n---");
  });
});

describe("unwrapSoftBreaks", () => {
  it("joins a wrapped paragraph and keeps blocks", () => {
    const text =
      "Find rivals of the\nproduct, then\nreturn a table.\n\n- one\n- two\n```\na\nb\n```";
    expect(unwrapSoftBreaks(text)).toBe(
      "Find rivals of the product, then return a table.\n\n- one\n- two\n```\na\nb\n```"
    );
  });
});
