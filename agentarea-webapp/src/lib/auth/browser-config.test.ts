import { getLocale } from "next-intl/server";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { getOryBrowserConfig } from "./browser-config";

vi.mock("next-intl/server", () => ({
  getLocale: vi.fn(),
}));

vi.mock("@/env", () => ({
  env: { ORY_SDK_URL: "http://kratos.internal:4433" },
}));

describe("getOryBrowserConfig", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    delete process.env.ORY_BROWSER_URL;
  });

  it("passes a supported app locale through to Ory Elements", async () => {
    vi.mocked(getLocale).mockResolvedValue("ru");

    const config = await getOryBrowserConfig();

    expect(config.intl?.locale).toBe("ru");
    expect(config.project.default_locale).toBe("ru");
  });

  it("falls back to English for locales Ory Elements is not translated into", async () => {
    vi.mocked(getLocale).mockResolvedValue("de");

    const config = await getOryBrowserConfig();

    expect(config.intl?.locale).toBe("en");
    expect(config.project.default_locale).toBe("en");
  });

  it("advertises exactly the bundled locales", async () => {
    vi.mocked(getLocale).mockResolvedValue("en");

    const config = await getOryBrowserConfig();

    expect(config.project.enabled_locales).toEqual(["en", "ru"]);
  });

  it("prefers the browser-reachable Ory URL when one is configured", async () => {
    vi.mocked(getLocale).mockResolvedValue("en");
    process.env.ORY_BROWSER_URL = "https://auth.example.com";

    const config = await getOryBrowserConfig();

    expect(config.sdk?.url).toBe("https://auth.example.com");
  });

  it("falls back to the in-cluster Ory URL when no browser URL is set", async () => {
    vi.mocked(getLocale).mockResolvedValue("en");

    const config = await getOryBrowserConfig();

    expect(config.sdk?.url).toBe("http://kratos.internal:4433");
  });
});
