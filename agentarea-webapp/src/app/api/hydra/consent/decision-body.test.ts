import { describe, expect, it } from "vitest";
import { consentDecisionBody } from "./decision-body";

const consentRequest = {
  subject: "user-a",
  requested_scope: ["openid", "offline_access"],
  requested_access_token_audience: ["https://api.agentarea.ru"],
  client: { audience: ["https://other.example"] },
};

describe("consentDecisionBody", () => {
  it("grants exactly what the client requested", () => {
    expect(consentDecisionBody("accept", consentRequest)).toEqual({
      grant_scope: ["openid", "offline_access"],
      grant_access_token_audience: ["https://api.agentarea.ru"],
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
});
