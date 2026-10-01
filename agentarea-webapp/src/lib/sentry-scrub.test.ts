import { describe, expect, it } from "vitest";
import {
  scrubBreadcrumbUrls,
  scrubEventUrls,
  stripQuery,
} from "./sentry-scrub";

describe("stripQuery", () => {
  it("drops the query string", () => {
    expect(
      stripQuery("https://app.example.com/w/a/dashboard?invitation=tok")
    ).toBe("https://app.example.com/w/a/dashboard");
  });

  it("drops the fragment", () => {
    expect(stripQuery("/auth/login#flow=abc")).toBe("/auth/login");
  });

  it("drops both when the fragment follows the query", () => {
    expect(stripQuery("/a?b=1#c")).toBe("/a");
  });

  it("leaves a URL without either unchanged", () => {
    expect(stripQuery("/w/a/members")).toBe("/w/a/members");
  });
});

describe("scrubEventUrls", () => {
  it("strips the request URL and drops the parsed query string", () => {
    const event = scrubEventUrls({
      request: {
        url: "https://app.example.com/w/a/dashboard?invitation=tok",
        query_string: "invitation=tok",
      },
    });
    expect(event.request).toEqual({
      url: "https://app.example.com/w/a/dashboard",
    });
  });

  it("strips the Next.js request path recorded for server errors", () => {
    const event = scrubEventUrls({
      contexts: {
        nextjs: {
          request_path: "/w/a/dashboard?invitation=tok",
          router_path: "/w/[workspace]/dashboard",
        },
      },
    });
    expect(event.contexts?.nextjs).toEqual({
      request_path: "/w/a/dashboard",
      router_path: "/w/[workspace]/dashboard",
    });
  });

  it("accepts an event with neither", () => {
    expect(scrubEventUrls({ message: "x", contexts: {} })).toEqual({
      message: "x",
      contexts: {},
    });
  });
});

describe("scrubBreadcrumbUrls", () => {
  it("strips fetch and XHR URLs", () => {
    const crumb = scrubBreadcrumbUrls({
      category: "fetch",
      data: {
        method: "GET",
        url: "/api/x?consent_challenge=abc",
        status_code: 200,
      },
    });
    expect(crumb.data).toEqual({
      method: "GET",
      url: "/api/x",
      status_code: 200,
    });
  });

  it("strips both ends of a navigation", () => {
    const crumb = scrubBreadcrumbUrls({
      category: "navigation",
      data: {
        from: "/auth/login?flow=f1",
        to: "/w/a/dashboard?invitation=tok",
      },
    });
    expect(crumb.data).toEqual({ from: "/auth/login", to: "/w/a/dashboard" });
  });

  it("leaves non-string and missing data alone", () => {
    expect(
      scrubBreadcrumbUrls({ category: "ui.click", data: undefined })
    ).toEqual({ category: "ui.click", data: undefined });
    expect(scrubBreadcrumbUrls({ data: { url: 5 } })).toEqual({
      data: { url: 5 },
    });
  });
});
