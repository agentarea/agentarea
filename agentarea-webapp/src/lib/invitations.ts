export const INVITATION_QUERY_PARAM = "invitation";

const INVITATION_LANDING_PATH = "/dashboard";

export type InvitationProblem =
  | "missing_token"
  | "not_found"
  | "wrong_account"
  | "expired"
  | "revoked"
  | "already_accepted"
  | "unknown";

export type InvitationFailure = {
  problem: InvitationProblem;
  message: string;
};

/**
 * Where an invitation link lands: the app, with the invitation dialog open.
 *
 * A missing token still opens the dialog, as an empty value, so the invitee
 * is told the link is broken instead of arriving at the dashboard unaware.
 */
export function invitationDialogPath(token: string | null | undefined) {
  const params = new URLSearchParams({
    [INVITATION_QUERY_PARAM]: token?.trim() ?? "",
  });
  return `${INVITATION_LANDING_PATH}?${params}`;
}

/**
 * Name the reason an invitation cannot be previewed or accepted, from the
 * backend's status and detail. Anything not recognised stays "unknown" so the
 * dialog shows the raw message rather than a confident wrong one.
 */
export function classifyInvitationError(
  status: number | undefined,
  detail: string
): InvitationProblem {
  switch (status) {
    case 404:
      return "not_found";
    case 403:
      return detail === "invitation addressed to another account"
        ? "wrong_account"
        : "unknown";
    case 409:
      return detail === "invitation already accepted"
        ? "already_accepted"
        : "unknown";
    case 410:
      if (detail === "invitation expired") return "expired";
      if (detail === "invitation revoked") return "revoked";
      return "unknown";
    default:
      return "unknown";
  }
}

/** The inviter as a person reads them: their name, else their email. */
export function inviterLabel(inviter: {
  inviter_display_name: string | null;
  inviter_email: string | null;
}): string | null {
  return (
    inviter.inviter_display_name?.trim() ||
    inviter.inviter_email?.trim() ||
    null
  );
}
