import { describe, expect, it } from "vitest";
import {
  isPersonalWorkspace,
  personalWorkspace,
  withWorkspaceQuery,
  type Workspace,
} from "./workspaces";

const personal: Workspace = {
  id: "user-1",
  slug: "user-1",
  name: "Personal",
  owner_user_id: "user-1",
  can_administer: true,
};
const acme: Workspace = {
  id: "ws-acme",
  slug: "acme",
  name: "Acme",
  owner_user_id: "user-1",
  can_administer: true,
};
const globex: Workspace = {
  id: "ws-globex",
  slug: "globex",
  name: "Globex",
  owner_user_id: "user-2",
  can_administer: false,
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

describe("personalWorkspace", () => {
  it("returns the workspace whose id is its owner's", () => {
    expect(personalWorkspace([acme, personal, globex])).toBe(personal);
  });

  it("returns null when the user has no personal workspace", () => {
    expect(personalWorkspace([acme, globex])).toBeNull();
  });
});

describe("withWorkspaceQuery", () => {
  it("appends the workspace to a URL", () => {
    expect(withWorkspaceQuery("/api/sse/x", "acme")).toBe(
      "/api/sse/x?workspace=acme"
    );
    expect(withWorkspaceQuery("/api/proxy/x?a=1", "a b")).toBe(
      "/api/proxy/x?a=1&workspace=a%20b"
    );
  });

  it("leaves the URL alone without a workspace", () => {
    expect(withWorkspaceQuery("/api/sse/x", null)).toBe("/api/sse/x");
  });
});
