import { describe, expect, it } from "vitest";

import {
  authModeFromValidation,
  modeFromMethods,
  withDeclaredFields,
} from "./auth-mode";

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

describe("withDeclaredFields", () => {
  it("offers OAuth next to the declared fields when the probe reports it", () => {
    // GitHub: the spec declares an Authorization header, the server takes OAuth.
    expect(withDeclaredFields("both", true)).toBe("both");
    expect(withDeclaredFields("oauth", true)).toBe("both");
  });

  it("keeps the declared fields when the probe reports no OAuth", () => {
    expect(withDeclaredFields("credentials", true)).toBe("fields");
    expect(withDeclaredFields("none", true)).toBe("fields");
    expect(withDeclaredFields("error", true)).toBe("fields");
  });

  it("leaves a spec without declared fields to the probe", () => {
    expect(withDeclaredFields("oauth", false)).toBe("oauth");
    expect(withDeclaredFields("error", false)).toBe("error");
  });

  it("keeps waiting while the probe runs", () => {
    expect(withDeclaredFields("loading", true)).toBe("loading");
  });
});
