import { describe, expect, it } from "vitest";
import {
  isPersonalWorkspace,
  resolveActiveWorkspace,
  type Workspace,
} from "./workspaces";

const personal: Workspace = {
  id: "user-1",
  slug: "user-1",
  name: "Personal",
  owner_user_id: "user-1",
};
const acme: Workspace = {
  id: "ws-acme",
  slug: "acme",
  name: "Acme",
  owner_user_id: "user-1",
};
const globex: Workspace = {
  id: "ws-globex",
  slug: "globex",
  name: "Globex",
  owner_user_id: "user-2",
};

describe("isPersonalWorkspace", () => {
  it("recognises the workspace whose id is its owner's", () => {
    expect(isPersonalWorkspace(personal)).toBe(true);
  });

  it("does not treat a workspace you own as personal", () => {
    // Alice owns Acme, but it is a real shared workspace: ownership is not
    // the marker, the id being the owner's own id is.
    expect(isPersonalWorkspace(acme)).toBe(false);
  });
});

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
