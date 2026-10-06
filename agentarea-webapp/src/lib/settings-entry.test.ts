import { describe, expect, it } from "vitest";
import { settingsEntryHop } from "./settings-entry";

const kratosBrowserUrl = "http://localhost:4433";
const hop = (url: string, returnWorkspace?: string) =>
  settingsEntryHop(new URL(url, "http://localhost:3000"), {
    kratosBrowserUrl,
    returnWorkspace,
  });

describe("settingsEntryHop", () => {
  it("sends a workspace settings page without a flow to Kratos, keeping its query", () => {
    expect(hop("/w/acme/settings?source=nav")).toEqual({
      kind: "to-kratos",
      location:
        "http://localhost:4433/self-service/settings/browser?source=nav",
      workspace: "acme",
    });
  });

  it("leaves a settings page that already has a flow alone", () => {
    expect(hop("/w/acme/settings?flow=f1")).toBeNull();
  });

  it("leaves the other settings pages alone", () => {
    expect(hop("/w/acme/settings/api-keys")).toBeNull();
    expect(hop("/w/acme/agents")).toBeNull();
  });

  it("brings Kratos' return to the workspace the trip started from", () => {
    expect(hop("/settings?flow=f1&return_to=x", "acme")).toEqual({
      kind: "to-workspace",
      location: "/w/acme/settings?flow=f1&return_to=x",
    });
  });

  it("keeps a remembered workspace inside the /w/ path", () => {
    expect(hop("/settings?flow=f1", "../../evil.com")).toEqual({
      kind: "to-workspace",
      location: "/w/..%2F..%2Fevil.com/settings?flow=f1",
    });
  });

  it("falls back to the page when no workspace is remembered or no flow came back", () => {
    expect(hop("/settings?flow=f1")).toBeNull();
    expect(hop("/settings", "acme")).toBeNull();
  });
});
