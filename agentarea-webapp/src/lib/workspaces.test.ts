import { describe, expect, it } from "vitest";
import { resolveActiveWorkspace, type Workspace } from "./workspaces";

const personal: Workspace = {
  id: "user-1",
  slug: "user-1",
  name: "Personal",
  type: "personal",
};
const acme: Workspace = {
  id: "ws-acme",
  slug: "acme",
  name: "Acme",
  type: "shared",
};
const globex: Workspace = {
  id: "ws-globex",
  slug: "globex",
  name: "Globex",
  type: "shared",
};

describe("resolveActiveWorkspace", () => {
  it("returns the workspace matching the preferred slug", () => {
    expect(resolveActiveWorkspace([personal, acme, globex], "globex")).toBe(
      globex
    );
  });

  it("falls back to the personal workspace when the slug is unknown", () => {
    // A stale cookie must not win: the backend 403s every request made with a
    // slug the user is no longer a member of.
    expect(resolveActiveWorkspace([personal, acme], "left-this-one")).toBe(
      personal
    );
  });

  it("falls back to the personal workspace when no slug is set", () => {
    expect(resolveActiveWorkspace([acme, personal], null)).toBe(personal);
  });

  it("falls back to the first workspace when there is no personal one", () => {
    expect(resolveActiveWorkspace([acme, globex], undefined)).toBe(acme);
  });

  it("returns null when the user has no workspaces", () => {
    expect(resolveActiveWorkspace([], "acme")).toBeNull();
  });
});
