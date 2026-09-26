import { describe, expect, it } from "vitest";
import {
  fillWorkspace,
  InvalidWorkspaceError,
  isWorkspaceScoped,
  MissingWorkspaceError,
} from "./workspace-url";

describe("fillWorkspace", () => {
  it("fills the template placeholder", () => {
    expect(
      fillWorkspace("http://api/v1/workspaces/{workspace}/agents", "acme")
    ).toBe("http://api/v1/workspaces/acme/agents");
  });

  it("fills the placeholder a Request has percent-encoded", () => {
    const url = new Request("http://api/v1/workspaces/{workspace}/agents").url;
    expect(fillWorkspace(url, "acme")).toBe(
      "http://api/v1/workspaces/acme/agents"
    );
    expect(fillWorkspace("/v1/workspaces/%7bworkspace%7d/x", "acme")).toBe(
      "/v1/workspaces/acme/x"
    );
  });

  it("accepts the backend's slug shape", () => {
    expect(fillWorkspace("/v1/workspaces/{workspace}/x", "team-42")).toBe(
      "/v1/workspaces/team-42/x"
    );
    expect(fillWorkspace("/v1/workspaces/{workspace}/x", "a".repeat(120))).toBe(
      `/v1/workspaces/${"a".repeat(120)}/x`
    );
  });

  it("rejects a slug that could leave the workspace segment", () => {
    for (const slug of [
      "..",
      "%2e%2e",
      "a/b",
      "a%2Fb",
      "Acme",
      "a b",
      "-acme",
      "acme-",
      "a--b",
      "a".repeat(121),
    ]) {
      expect(() => fillWorkspace("/v1/workspaces/{workspace}/x", slug)).toThrow(
        InvalidWorkspaceError
      );
    }
  });

  it("leaves the query string alone", () => {
    expect(
      fillWorkspace("/v1/workspaces/{workspace}/x?q=%7Bworkspace%7D", "acme")
    ).toBe("/v1/workspaces/acme/x?q=%7Bworkspace%7D");
    expect(fillWorkspace("/v1/workspaces?q={workspace}", null)).toBe(
      "/v1/workspaces?q={workspace}"
    );
  });

  it("returns a workspace-less URL unchanged, slug or not", () => {
    expect(fillWorkspace("/v1/workspaces", "acme")).toBe("/v1/workspaces");
    expect(fillWorkspace("/v1/invitations/preview", null)).toBe(
      "/v1/invitations/preview"
    );
  });

  it("throws when a workspace-scoped URL has no slug", () => {
    for (const slug of [null, undefined, ""]) {
      expect(() => fillWorkspace("/v1/workspaces/{workspace}/x", slug)).toThrow(
        MissingWorkspaceError
      );
    }
  });
});

describe("isWorkspaceScoped", () => {
  it("looks at the path only", () => {
    expect(isWorkspaceScoped("/v1/workspaces/{workspace}/x")).toBe(true);
    expect(isWorkspaceScoped("/v1/workspaces/%7Bworkspace%7D/x")).toBe(true);
    expect(isWorkspaceScoped("/v1/workspaces/acme/x")).toBe(false);
    expect(isWorkspaceScoped("/v1/x?q={workspace}")).toBe(false);
  });
});
