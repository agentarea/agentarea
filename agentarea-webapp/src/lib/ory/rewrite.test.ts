import { beforeEach, describe, expect, it, vi } from "vitest";
import { rewriteJsonResponse, rewriteUrls } from "./rewrite";
import type { OryMiddlewareOptions } from "./types";
import { orySdkUrl } from "./url";

vi.mock("./url", async (importOriginal) => {
  const actual = await importOriginal<typeof import("./url")>();
  return {
    ...actual,
    orySdkUrl: vi.fn(),
  };
});

describe("rewriteUrls", () => {
  const config: OryMiddlewareOptions = {
    project: {
      recovery_ui_url: "/custom/recovery",
      registration_ui_url: "/custom/registration",
      login_ui_url: "/custom/login",
      verification_ui_url: "/custom/verification",
      settings_ui_url: "/custom/settings",
      error_ui_url: "/custom/error",
      default_locale: "en",
      enabled_locales: ["en"],
      default_redirect_url: "/",
      locale_behavior: "force_default",
      name: "AgentArea",
      registration_enabled: true,
      verification_enabled: true,
      recovery_enabled: true,
      translations: [],
    },
  };

  it("rewrites URLs based on config overrides", () => {
    expect(
      rewriteUrls(
        "https://example.com/ui/login",
        "https://example.com",
        "https://self.com",
        config
      )
    ).toBe("https://self.com/custom/login");
  });

  it("replaces the base URL with the self URL", () => {
    expect(
      rewriteUrls(
        "https://example.com/some/path",
        "https://example.com",
        "https://self.com",
        config
      )
    ).toBe("https://self.com/some/path");
  });
});

describe("rewriteJsonResponse", () => {
  beforeEach(() => {
    vi.mocked(orySdkUrl).mockReturnValue("https://ory-sdk-url.com");
  });

  it("rewrites URLs in a JSON response", () => {
    const result = rewriteJsonResponse(
      {
        url: "https://ory-sdk-url.com/path",
        nested: {
          url: "https://ory-sdk-url.com/nested/path",
        },
      },
      "https://proxy-url.com"
    );

    expect(result).toEqual({
      url: "https://proxy-url.com/path",
      nested: {
        url: "https://proxy-url.com/nested/path",
      },
    });
  });

  it("removes undefined values from a JSON response", () => {
    const result = rewriteJsonResponse({
      key1: "value1",
      key2: undefined,
      nested: {
        key3: "value3",
        key4: undefined,
      },
    });

    expect(result).toEqual({
      key1: "value1",
      nested: {
        key3: "value3",
      },
    });
  });

  it("handles arrays in a JSON response", () => {
    const result = rewriteJsonResponse(
      {
        array: [
          "https://ory-sdk-url.com/item1",
          undefined,
          {
            url: "https://ory-sdk-url.com/item2",
          },
        ],
      },
      "https://proxy-url.com"
    );

    expect(result).toEqual({
      array: [
        "https://proxy-url.com/item1",
        {
          url: "https://proxy-url.com/item2",
        },
      ],
    });
  });
});
