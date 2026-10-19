import { describe, expect, it } from "vitest";
import { deepLinkPath } from "./deep-link";

describe("deepLinkPath", () => {
  it("carries the value encoded", () => {
    expect(
      deepLinkPath(
        "/skills/create",
        "github",
        "https://github.com/acme/skills/tree/main/pdf"
      )
    ).toBe(
      "/skills/create?github=https%3A%2F%2Fgithub.com%2Facme%2Fskills%2Ftree%2Fmain%2Fpdf"
    );
  });

  it("keeps only the first of a repeated value", () => {
    expect(
      deepLinkPath("/bundles/import", "src", [
        "https://example.com/a.yaml",
        "https://example.com/b.yaml",
      ])
    ).toBe("/bundles/import?src=https%3A%2F%2Fexample.com%2Fa.yaml");
  });

  it("cannot smuggle a second parameter", () => {
    expect(deepLinkPath("/bundles/import", "src", "x&from=evil")).toBe(
      "/bundles/import?src=x%26from%3Devil"
    );
  });

  it.each([undefined, null, "", []])(
    "opens the bare page without a value (%j)",
    (value) => {
      expect(deepLinkPath("/bundles/import", "src", value)).toBe(
        "/bundles/import"
      );
    }
  );
});
