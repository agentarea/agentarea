import { describe, expect, it } from "vitest";
import { parseGithubSkillUrl, skillImportPath } from "./skill-import";

describe("parseGithubSkillUrl", () => {
  it("accepts a repository", () => {
    expect(parseGithubSkillUrl("https://github.com/acme/skills")).toBe(
      "https://github.com/acme/skills"
    );
  });

  it("accepts a folder pinned to a ref", () => {
    expect(
      parseGithubSkillUrl(
        "https://github.com/acme/skills/tree/4f1c2e9/skills/pdf-tools/"
      )
    ).toBe("https://github.com/acme/skills/tree/4f1c2e9/skills/pdf-tools");
  });

  it("accepts a blob link to the SKILL.md file", () => {
    expect(
      parseGithubSkillUrl("https://github.com/acme/skills/blob/main/pdf/SKILL.md")
    ).toBe("https://github.com/acme/skills/blob/main/pdf/SKILL.md");
  });

  it.each([
    ["missing", null],
    ["empty", ""],
    ["not a URL", "acme/skills"],
    ["http", "http://github.com/acme/skills"],
    ["another host", "https://gitlab.com/acme/skills"],
    ["a lookalike host", "https://github.com.evil.example/acme/skills"],
    ["a subdomain", "https://gist.github.com/acme/skills"],
    ["credentials", "https://user:pw@github.com/acme/skills"],
    ["a port", "https://github.com:8443/acme/skills"],
    ["a query", "https://github.com/acme/skills?tab=readme"],
    ["a fragment", "https://github.com/acme/skills#readme"],
    ["a javascript: URL", "javascript:alert(1)"],
    ["an owner only", "https://github.com/acme"],
    ["a non-tree page", "https://github.com/acme/skills/issues/1"],
    ["a tree without a ref", "https://github.com/acme/skills/tree"],
    ["markup in the owner", "https://github.com/<script>/skills"],
    ["an empty path segment", "https://github.com/acme/skills/tree/main//pdf"],
    ["an oversized URL", `https://github.com/acme/skills/tree/main/${"a".repeat(2100)}`],
  ])("rejects %s", (_, raw) => {
    expect(parseGithubSkillUrl(raw)).toBeNull();
  });

  it("does not let dot segments climb out of the repository", () => {
    expect(
      parseGithubSkillUrl("https://github.com/acme/skills/../../other/repo")
    ).toBe("https://github.com/other/repo");
  });
});

describe("skillImportPath", () => {
  it("lands on the create form with the URL encoded", () => {
    expect(
      skillImportPath("https://github.com/acme/skills/tree/main/pdf")
    ).toBe(
      "/skills/create?github=https%3A%2F%2Fgithub.com%2Facme%2Fskills%2Ftree%2Fmain%2Fpdf"
    );
  });

  it("opens the plain create form without a URL", () => {
    expect(skillImportPath(undefined)).toBe("/skills/create");
  });
});
