import { describe, expect, it } from "vitest";
import { loginDecision } from "./decision";

describe("loginDecision", () => {
  it("accepts a fresh login as the session's identity, remembering nothing", () => {
    expect(loginDecision({ skip: false }, "user-a")).toEqual({
      action: "accept",
      body: { subject: "user-a" },
    });
  });

  it("accepts a skipped login whose subject is the session's identity", () => {
    expect(loginDecision({ skip: true, subject: "user-a" }, "user-a")).toEqual(
      { action: "accept", body: { subject: "user-a" } }
    );
  });

  it("rejects a skipped login remembered for another user", () => {
    const decision = loginDecision(
      { skip: true, subject: "user-a" },
      "user-b"
    );
    expect(decision.action).toBe("reject");
    expect(decision.body).toMatchObject({ error: "login_required" });
  });
});
