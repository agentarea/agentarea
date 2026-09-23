import { describe, expect, it } from "vitest";
import { getMcpConnectionState, getOpenApiConnectionState } from "./state";

const HOUR = 3_600_000;
const iso = (msAgo: number) => new Date(Date.now() - msAgo).toISOString();

describe("getMcpConnectionState", () => {
  it("reports a connection whose last call failed as failing, not verified", () => {
    // The setup probe succeeded once and is never refreshed — the call is the
    // newer fact and the one an operator needs to see.
    const state = getMcpConnectionState({
      verification: { status: "succeeded", at: iso(72 * HOUR) },
      last_dispatch: { status: "failed", at: iso(2 * HOUR), error: "401" },
      toolCount: 42,
    });

    expect(state.key).toBe("failing");
    expect(state.tone).toBe("danger");
  });

  it("prefers the newer signal when the probe failed after the last good call", () => {
    const state = getMcpConnectionState({
      verification: { status: "failed", at: iso(1 * HOUR) },
      last_dispatch: { status: "succeeded", at: iso(5 * HOUR), error: null },
      toolCount: 42,
    });

    expect(state.key).toBe("broken");
  });

  it("prefers the newer signal when a call succeeded after a stale failed probe", () => {
    const state = getMcpConnectionState({
      verification: { status: "failed", at: iso(48 * HOUR) },
      last_dispatch: { status: "succeeded", at: iso(1 * HOUR), error: null },
      toolCount: 42,
    });

    expect(state.key).toBe("working");
  });

  it("separates a configured-but-never-called connection from a working one", () => {
    const state = getMcpConnectionState({
      verification: { status: "succeeded", at: iso(24 * HOUR) },
      last_dispatch: null,
      toolCount: 42,
    });

    expect(state.key).toBe("ready");
  });

  it("marks a connection with no tools and no probe as not set up", () => {
    expect(
      getMcpConnectionState({
        verification: { status: "never_attempted", at: null },
        last_dispatch: null,
        toolCount: 0,
      }).key
    ).toBe("unconfigured");
  });

  it("keeps an in-flight probe distinct from a verdict", () => {
    const state = getMcpConnectionState({
      verification: { status: "in_progress", at: iso(0) },
      last_dispatch: { status: "succeeded", at: iso(HOUR), error: null },
      toolCount: 42,
    });

    expect(state.key).toBe("verifying");
    expect(state.pulse).toBe(true);
  });
});

describe("getOpenApiConnectionState", () => {
  it("treats a reachable spec with tools as ready, not working", () => {
    expect(getOpenApiConnectionState("connected", 30).key).toBe("ready");
  });

  it("treats an errored connection as broken", () => {
    expect(getOpenApiConnectionState("error", 0).key).toBe("broken");
  });
});
