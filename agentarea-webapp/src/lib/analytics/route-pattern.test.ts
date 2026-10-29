import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { PAGE_ROUTES, routePattern } from "./route-pattern";

// Pages that only redirect elsewhere; the page they land on is the view.
const REDIRECT_ONLY = [
  "/",
  "/admin/provider-configs",
  "/events/event/*",
  "/tasks/*/memory",
  "/tasks/*/metrics",
];

function pageRoutesOnDisk(dir: string, route: string[] = []): string[] {
  const entries = readdirSync(dir, { withFileTypes: true });
  const here = entries.some((entry) => entry.name === "page.tsx")
    ? [`/${route.join("/")}`]
    : [];
  const below = entries
    .filter((entry) => entry.isDirectory())
    .flatMap((entry) => {
      const name = entry.name;
      const next = name.startsWith("(")
        ? route
        : [...route, name.startsWith("[") ? "*" : name];
      return pageRoutesOnDisk(`${dir}/${name}`, next);
    });
  return [...here, ...below];
}

describe("PAGE_ROUTES", () => {
  it("lists every workspace page that is not a redirect", () => {
    // A page missing from the list is never counted.
    const root = fileURLToPath(
      new URL("../../app/w/[workspace]", import.meta.url)
    );
    const onDisk = pageRoutesOnDisk(root)
      .filter((route) => !REDIRECT_ONLY.includes(route))
      .sort();
    expect([...PAGE_ROUTES].sort()).toEqual(onDisk);
  });
});

describe("routePattern", () => {
  it.each([
    [
      "/w/acme/connections/create/86e0ea70-1c2d-4f5e-9a8b-0c1d2e3f4a5b",
      "/w/*/connections/create/*",
    ],
    ["/w/acme/agents", "/w/*/agents"],
    ["/w/acme/agents/", "/w/*/agents"],
    ["/w/acme/agents/create", "/w/*/agents/create"],
    ["/w/acme/agents/42", "/w/*/agents/*"],
    ["/w/acme/agents/42/settings", "/w/*/agents/*/settings"],
    ["/w/acme/connections/add", "/w/*/connections/add"],
    ["/w/acme/connections/abc", "/w/*/connections/*"],
    ["/w/acme/policies/new", "/w/*/policies/new"],
    ["/w/acme/connect/catalog/github", "/w/*/connect/catalog/*"],
    ["/w/acme/connect/inst-1", "/w/*/connect/*"],
    ["/w/acme/apps/inst-1/search", "/w/*/apps/*/*"],
    ["/w/acme/models", "/w/*/models"],
    ["/w/acme/models/specs", "/w/*/models/specs"],
    ["/w/acme/tasks/7?tab=events#top", "/w/*/tasks/*"],
    ["/w/my%20team/dashboard", "/w/*/dashboard"],
  ])("%s → %s", (pathname, pattern) => {
    expect(routePattern(pathname)).toBe(pattern);
  });

  it.each([
    "/",
    "/w",
    "/w/acme",
    "/w//dashboard",
    "/w/acme/agents//settings",
    "/w/acme/admin/provider-configs",
    "/w/acme/tasks/7/metrics",
    "/w/acme/nope",
    "/w/acme/agents/1/2/3",
    "/auth/login",
    "/invite",
    "/settings",
    "/api/proxy/v1/agents",
    "/_next/static/chunks/main.js",
    "/favicon.ico",
    "/dashboard",
  ])("%s → null", (pathname) => {
    expect(routePattern(pathname)).toBeNull();
  });
});
