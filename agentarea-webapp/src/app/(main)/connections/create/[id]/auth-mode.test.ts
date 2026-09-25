import { describe, expect, it } from "vitest";

import { authModeFromValidation, modeFromMethods } from "./auth-mode";

describe("modeFromMethods", () => {
  it("offers both when OAuth and manual credentials work", () => {
    expect(modeFromMethods(["oauth", "credentials"])).toBe("both");
  });

  it("treats an open endpoint as needing nothing", () => {
    expect(modeFromMethods(["none"])).toBe("none");
  });
});

describe("authModeFromValidation", () => {
  it("asks to connect when a server lists tools openly but advertises OAuth", () => {
    // Gmail: tools/list succeeds without a token, every tool call 401s.
    expect(
      authModeFromValidation({
        valid: true,
        auth_methods: ["oauth", "credentials"],
      })
    ).toBe("both");
  });

  it("creates directly for an endpoint that is open and advertises nothing", () => {
    expect(authModeFromValidation({ valid: true })).toBe("none");
  });

  it("renders the form the auth failure points at", () => {
    expect(
      authModeFromValidation({ valid: false, auth_methods: ["credentials"] })
    ).toBe("credentials");
  });

  it("is an error when the failure says nothing about auth", () => {
    expect(
      authModeFromValidation({ valid: false, errors: ["Connection failed"] })
    ).toBe("error");
  });
});
