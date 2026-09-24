import { describe, expect, it } from "vitest";
import { sessionMatchesConsentSubject } from "./subject-match";

describe("sessionMatchesConsentSubject", () => {
  it("matches when the session identity is the consent request's subject", () => {
    expect(sessionMatchesConsentSubject("user-a", "user-a")).toBe(true);
  });

  it("rejects a different user's live session for this consent request", () => {
    expect(sessionMatchesConsentSubject("user-b", "user-a")).toBe(false);
  });

  it("rejects when there is no live session", () => {
    expect(sessionMatchesConsentSubject(null, "user-a")).toBe(false);
  });

  it("rejects when the consent request carries no subject", () => {
    expect(sessionMatchesConsentSubject("user-a", undefined)).toBe(false);
  });
});
