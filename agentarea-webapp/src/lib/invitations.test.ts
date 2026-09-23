import { describe, expect, it } from "vitest";
import {
  classifyInvitationError,
  invitationDialogPath,
  inviterLabel,
} from "./invitations";

describe("invitationDialogPath", () => {
  it("opens the dialog in the app with the token encoded", () => {
    expect(invitationDialogPath("a+b/c=")).toBe(
      "/dashboard?invitation=a%2Bb%2Fc%3D"
    );
  });

  it("keeps the dialog open for a link that lost its token", () => {
    expect(invitationDialogPath(undefined)).toBe("/dashboard?invitation=");
    expect(invitationDialogPath("  ")).toBe("/dashboard?invitation=");
  });
});

describe("classifyInvitationError", () => {
  it.each([
    [404, "invalid token", "not_found"],
    [403, "invitation addressed to another account", "wrong_account"],
    [409, "invitation already accepted", "already_accepted"],
    [410, "invitation expired", "expired"],
    [410, "invitation revoked", "revoked"],
  ] as const)("reads %i %s as %s", (status, detail, problem) => {
    expect(classifyInvitationError(status, detail)).toBe(problem);
  });

  it("does not call an unrelated 403 a wrong account", () => {
    expect(classifyInvitationError(403, "Access denied")).toBe("unknown");
  });

  it("leaves a gone invitation with an unknown reason unknown", () => {
    expect(classifyInvitationError(410, "gone")).toBe("unknown");
  });

  it("treats a server failure as unknown", () => {
    expect(classifyInvitationError(503, "graph unavailable")).toBe("unknown");
    expect(classifyInvitationError(undefined, "")).toBe("unknown");
  });
});

describe("inviterLabel", () => {
  it("prefers the inviter's name", () => {
    expect(
      inviterLabel({
        inviter_display_name: "Artem Astapenko",
        inviter_email: "artem@agentarea.ai",
      })
    ).toBe("Artem Astapenko");
  });

  it("shows the email only when there is no name", () => {
    expect(
      inviterLabel({
        inviter_display_name: " ",
        inviter_email: "artem@agentarea.ai",
      })
    ).toBe("artem@agentarea.ai");
  });

  it("admits an inviter nobody could resolve", () => {
    expect(
      inviterLabel({ inviter_display_name: null, inviter_email: null })
    ).toBeNull();
  });
});
