import { describe, expect, it } from "vitest";
import { identityClaims } from "./identity-claims";

const identity = {
  id: "user-a",
  traits: {
    email: "Ann@Example.com",
    name: { first: "Ann", last: "Lee" },
    username: "ann",
    picture: "https://cdn.example/ann.png",
  },
  verifiedEmails: ["ann@example.com"],
};

describe("identityClaims", () => {
  it("gives email and its verification under the email scope only", () => {
    expect(identityClaims(["openid", "email"], identity)).toEqual({
      email: "Ann@Example.com",
      email_verified: true,
    });
  });

  it("gives the profile claims under the profile scope only", () => {
    expect(identityClaims(["openid", "profile"], identity)).toEqual({
      name: "Ann Lee",
      given_name: "Ann",
      family_name: "Lee",
      preferred_username: "ann",
      picture: "https://cdn.example/ann.png",
    });
  });

  it("gives nothing without email or profile", () => {
    expect(identityClaims(["openid", "offline_access"], identity)).toEqual({});
  });

  it("marks an unverified address as such", () => {
    expect(
      identityClaims(["email"], { ...identity, verifiedEmails: [] })
    ).toEqual({ email: "Ann@Example.com", email_verified: false });
  });

  it("leaves out traits that are empty", () => {
    expect(
      identityClaims(["email", "profile"], {
        id: "user-b",
        traits: { email: "b@example.com", name: { first: " ", last: "" } },
        verifiedEmails: [],
      })
    ).toEqual({ email: "b@example.com", email_verified: false });
  });
});
