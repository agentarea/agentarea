import { readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  isWorkspaceRoute,
  prefixWorkspaceHref,
  rootLandingPath,
  stripWorkspacePrefix,
  WORKSPACE_ROUTES,
  workspacePath,
  workspaceSection,
  workspaceSlugFromPath,
} from "./workspace-routes";

describe("WORKSPACE_ROUTES", () => {
  it("lists exactly the top-level workspace route directories", () => {
    // A new page directory missing from the list would render its links
    // unprefixed, and those land in whichever workspace was used last.
    const dir = fileURLToPath(
      new URL("../app/w/[workspace]/(main)", import.meta.url)
    );
    const onDisk = readdirSync(dir, { withFileTypes: true })
      .filter((entry) => entry.isDirectory() && !entry.name.startsWith("."))
      .map((entry) => entry.name)
      .sort();
    expect([...WORKSPACE_ROUTES].sort()).toEqual(onDisk);
  });
});

describe("isWorkspaceRoute", () => {
  it.each(["/agents", "/agents/1?tab=x", "/settings#keys", "/dashboard?q=1"])(
    "accepts %s",
    (path) => expect(isWorkspaceRoute(path)).toBe(true)
  );

  it.each([
    "/",
    "/auth/login",
    "/api/proxy/v1/x",
    "/invite?token=t",
    "/app-sandbox",
    "/w/acme/agents",
    "/agentsx",
    "//agents",
    "agents",
    "https://example.test/agents",
    "?page=2",
  ])("rejects %s", (path) => expect(isWorkspaceRoute(path)).toBe(false));
});

describe("workspacePath", () => {
  it("prefixes a path with the workspace", () => {
    expect(workspacePath("acme", "/agents/1?tab=x")).toBe(
      "/w/acme/agents/1?tab=x"
    );
  });

  it("maps the root to the workspace itself", () => {
    expect(workspacePath("acme", "/")).toBe("/w/acme");
  });

  it("encodes the slug", () => {
    expect(workspacePath("a b", "/agents")).toBe("/w/a%20b/agents");
  });
});

describe("prefixWorkspaceHref", () => {
  it("prefixes workspace routes when the slug is known", () => {
    expect(prefixWorkspaceHref("/tasks/1", "acme")).toBe("/w/acme/tasks/1");
  });

  it("leaves the href alone without a slug", () => {
    expect(prefixWorkspaceHref("/tasks/1", null)).toBe("/tasks/1");
  });

  it("leaves non-workspace targets alone", () => {
    expect(prefixWorkspaceHref("/auth/login", "acme")).toBe("/auth/login");
    expect(prefixWorkspaceHref("/w/other/tasks", "acme")).toBe(
      "/w/other/tasks"
    );
  });
});

describe("workspaceSlugFromPath", () => {
  it("reads the slug of a workspace page", () => {
    expect(workspaceSlugFromPath("/w/acme/agents/1")).toBe("acme");
    expect(workspaceSlugFromPath("/w/acme")).toBe("acme");
    expect(workspaceSlugFromPath("/w/a%20b/agents")).toBe("a b");
  });

  it("returns null elsewhere", () => {
    expect(workspaceSlugFromPath("/agents")).toBeNull();
    expect(workspaceSlugFromPath("/w")).toBeNull();
    expect(workspaceSlugFromPath("/w/")).toBeNull();
    expect(workspaceSlugFromPath("/wx/acme")).toBeNull();
  });
});

describe("stripWorkspacePrefix", () => {
  it("drops the /w/{slug} prefix", () => {
    expect(stripWorkspacePrefix("/w/acme/agents/1")).toBe("/agents/1");
    expect(stripWorkspacePrefix("/w/acme")).toBe("/");
  });

  it("leaves other paths unchanged", () => {
    expect(stripWorkspacePrefix("/auth/login")).toBe("/auth/login");
  });
});

describe("workspaceSection", () => {
  it("keeps the top-level section and drops the ids below it", () => {
    expect(workspaceSection("/w/acme/agents/123/settings")).toBe("/agents");
  });

  it("falls back to the dashboard off a workspace section", () => {
    expect(workspaceSection("/w/acme")).toBe("/dashboard");
    expect(workspaceSection("/invite")).toBe("/dashboard");
  });
});

describe("rootLandingPath", () => {
  it("lands on the dashboard by default", () => {
    expect(rootLandingPath(new URLSearchParams())).toBe("/dashboard");
    expect(rootLandingPath(new URLSearchParams("oauth=success"))).toBe(
      "/dashboard"
    );
  });

  it("carries an OAuth failure to the connections list", () => {
    expect(
      rootLandingPath(
        new URLSearchParams("oauth=error&reason=state expired&x=1")
      )
    ).toBe("/connections?oauth=error&reason=state+expired");
    expect(rootLandingPath(new URLSearchParams("oauth=error"))).toBe(
      "/connections?oauth=error"
    );
  });
});
