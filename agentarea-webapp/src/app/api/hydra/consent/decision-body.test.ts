import { describe, expect, it } from "vitest";
import { consentDecisionBody } from "./decision-body";

const consentRequest = {
  subject: "user-a",
  requested_scope: ["openid", "offline_access"],
  requested_access_token_audience: ["https://api.agentarea.ai"],
  client: { audience: ["https://other.example"] },
};

describe("consentDecisionBody", () => {
  it("grants exactly what the client requested", () => {
    expect(consentDecisionBody("accept", consentRequest)).toEqual({
      grant_scope: ["openid", "offline_access"],
      grant_access_token_audience: ["https://api.agentarea.ai"],
    });
  });

  it("falls back to the client's registered audience when none was requested", () => {
    expect(
      consentDecisionBody("accept", {
        ...consentRequest,
        requested_access_token_audience: [],
      })
    ).toEqual({
      grant_scope: ["openid", "offline_access"],
      grant_access_token_audience: ["https://other.example"],
    });
  });

  it("grants nothing when the request names no scope", () => {
    expect(
      consentDecisionBody("accept", { subject: "user-a" })
    ).toEqual({ grant_scope: [], grant_access_token_audience: [] });
  });

  it("rejects as access_denied", () => {
    expect(consentDecisionBody("reject", consentRequest)).toEqual({
      error: "access_denied",
      error_description: "The user denied the request",
    });
  });

  it("puts the granted identity claims into the ID token", () => {
    expect(
      consentDecisionBody(
        "accept",
        { ...consentRequest, requested_scope: ["openid", "email"] },
        { id: "user-a", traits: { email: "a@example.com" }, verifiedEmails: ["a@example.com"] }
      )
    ).toEqual({
      grant_scope: ["openid", "email"],
      grant_access_token_audience: ["https://api.agentarea.ai"],
      session: { id_token: { email: "a@example.com", email_verified: true } },
    });
  });

  it("sends no session when no granted scope carries a claim", () => {
    expect(
      consentDecisionBody("accept", consentRequest, {
        id: "user-a",
        traits: { email: "a@example.com" },
        verifiedEmails: [],
      })
    ).not.toHaveProperty("session");
  });
});
