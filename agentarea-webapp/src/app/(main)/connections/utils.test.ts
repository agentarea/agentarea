import { describe, expect, it } from "vitest";
import { getEffectiveMCPVerificationStatus } from "./utils";

/**
 * The connections list answers one question: does this connection work?
 *
 * That is what verification decided — credentials accepted, tools discovered.
 * It deliberately says nothing about whether a container happens to be warm
 * right now: workloads start on demand and are reaped when idle, so liveness is
 * the data plane's business and never a fact about the connection.
 */
describe("getEffectiveMCPVerificationStatus", () => {
  it("stays verified for an idle workload with no container running", () => {
    expect(
      getEffectiveMCPVerificationStatus({
        name: "telegram",
        verification: { status: "succeeded" },
      })
    ).toBe("succeeded");
  });

  it("reads discovered tools as proof, over a stale never_attempted", () => {
    expect(
      getEffectiveMCPVerificationStatus({
        name: "telegram",
        tools: [{ name: "send_message" }],
        verification: { status: "never_attempted" },
      })
    ).toBe("succeeded");
  });

  it("accepts tools recorded on the legacy json_spec", () => {
    expect(
      getEffectiveMCPVerificationStatus({
        name: "legacy",
        json_spec: { available_tools: [{ name: "fetch" }] },
        verification: null,
      })
    ).toBe("succeeded");
  });

  it.each(["failed", "in_progress"])(
    "never lets discovered tools paper over %s",
    (status) => {
      expect(
        getEffectiveMCPVerificationStatus({
          name: "telegram",
          tools: [{ name: "send_message" }],
          verification: { status },
        })
      ).toBe(status);
    }
  );

  it("treats a missing verification as never attempted", () => {
    expect(getEffectiveMCPVerificationStatus({ name: "fresh" })).toBe(
      "never_attempted"
    );
  });
});
