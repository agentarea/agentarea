import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { joinUrlPaths, orySdkUrl } from "./url";

describe("orySdkUrl", () => {
  const original = process.env.ORY_SDK_URL;

  beforeEach(() => {
    delete process.env.ORY_SDK_URL;
  });

  afterEach(() => {
    if (original === undefined) {
      delete process.env.ORY_SDK_URL;
    } else {
      process.env.ORY_SDK_URL = original;
    }
  });

  it("returns ORY_SDK_URL without a trailing slash", () => {
    process.env.ORY_SDK_URL = "https://example.com/";
    expect(orySdkUrl()).toBe("https://example.com");
  });

  it("throws when ORY_SDK_URL is not set", () => {
    expect(() => orySdkUrl()).toThrow(/ORY_SDK_URL is not set/);
  });
});

describe("joinUrlPaths", () => {
  it("joins a base URL and a relative URL", () => {
    expect(joinUrlPaths("https://example.com/api", "/v1/resource")).toBe(
      "https://example.com/api/v1/resource"
    );
  });

  it("handles a base URL with a trailing slash", () => {
    expect(joinUrlPaths("https://example.com/", "v1/resource")).toBe(
      "https://example.com/v1/resource"
    );
  });

  it("keeps the host of an absolute relative URL", () => {
    expect(
      joinUrlPaths("https://example.com/api", "https://another.com/resource")
    ).toBe("https://another.com/api/resource");
  });
});
