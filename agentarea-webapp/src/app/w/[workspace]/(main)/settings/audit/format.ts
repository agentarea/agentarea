/** What a verb did, as a colour: made, changed, took away, or waits on someone. */
const VERB_TONES: Record<string, string> = {
  create: "var(--status-success)",
  invite: "var(--status-success)",
  grant: "var(--status-success)",
  allowed: "var(--status-success)",
  approved: "var(--status-success)",
  update: "var(--status-info)",
  rotate: "var(--status-info)",
  signing_secret_rotate: "var(--status-info)",
  set_enabled: "var(--status-info)",
  delete: "var(--status-danger)",
  remove: "var(--status-danger)",
  revoke: "var(--status-danger)",
  invitation_revoke: "var(--status-danger)",
  denied: "var(--status-danger)",
  approval_required: "var(--status-attention)",
};

/** The last segment of an action: `secret.rotate` → `rotate`. */
export function auditVerb(action: string): string {
  return action.split(".").pop() || "";
}

/** The colour of an action's verb; anything unlisted stays neutral. */
export function auditVerbTone(action: string): string | undefined {
  return VERB_TONES[auditVerb(action)];
}
