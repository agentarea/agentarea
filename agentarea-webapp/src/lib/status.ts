/**
 * Every status in the app is drawn as one of these kinds. A kind fixes the
 * glyph and its colour (see `StatusIndicator`); the presentation helpers below
 * only pick a kind and a label, so no call site can pair an icon with a colour
 * of its own.
 */
export type StatusKind =
  /** Not set up, never attempted, or a value we don't recognise. */
  | "draft"
  /** Accepted, not started yet. */
  | "queued"
  /** Waiting for its moment. */
  | "scheduled"
  /** In flight: executing, starting, verifying. */
  | "running"
  /** Waiting on a person: input, approval, an unblock, a renewal. */
  | "attention"
  | "paused"
  /** Switched on and healthy. */
  | "active"
  /** Switched off or stopped. */
  | "off"
  /** Finished successfully. */
  | "done"
  | "failed"
  /** Ended by someone: cancelled, revoked, refunded, expired. */
  | "cancelled";

const MUTED = "hsl(var(--muted-foreground))";

/** The kinds as CSS colours, for what a Tailwind class can't reach — chart
 * strokes, inline marker styles. Matches `StatusIndicator`. */
export const STATUS_KIND_COLOR: Record<StatusKind, string> = {
  draft: MUTED,
  queued: MUTED,
  scheduled: MUTED,
  running: "var(--status-info)",
  attention: "var(--status-attention)",
  paused: MUTED,
  active: "var(--status-success)",
  off: MUTED,
  done: "hsl(var(--primary))",
  failed: "var(--status-danger)",
  cancelled: MUTED,
};

export type StatusIndicatorSize = "default" | "sm";

export type StatusPresentation = {
  label: string;
  labelKey?: string;
  kind: StatusKind;
};

export function normalizeStatus(status: string): string {
  return status.trim().toLowerCase();
}

function fallbackStatusPresentation(status: string): StatusPresentation {
  return { label: status, kind: "draft" };
}

export function getMcpVerificationStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "succeeded":
      return { label: "Verified", labelKey: "connected", kind: "active" };
    case "in_progress":
      return { label: "Verifying", labelKey: "starting", kind: "running" };
    case "failed":
      return { label: "Failed", labelKey: "error", kind: "failed" };
    case "never_attempted":
      return { label: "Not verified", labelKey: "setup", kind: "draft" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getMcpHealthStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "connected":
      return { label: "Connected", labelKey: "connected", kind: "active" };
    case "healthy":
      return { label: "Healthy", kind: "active" };
    // A server that runs is up — steady state, not work in flight.
    case "running":
      return { label: "Running", labelKey: "running", kind: "active" };
    case "starting":
    case "pending":
    case "in_progress":
      return { label: "Starting", labelKey: "starting", kind: "running" };
    case "setup":
    case "unknown":
      return { label: "Setup", labelKey: "setup", kind: "draft" };
    case "unhealthy":
      return { label: "Unhealthy", labelKey: "error", kind: "failed" };
    case "error":
      return { label: "Error", labelKey: "error", kind: "failed" };
    case "failed":
      return { label: "Failed", labelKey: "error", kind: "failed" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getOpenApiConnectionStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "active":
      return { label: "Active", kind: "active" };
    case "connected":
      return { label: "Connected", kind: "active" };
    case "succeeded":
      return { label: "Succeeded", kind: "active" };
    case "running":
      return { label: "Running", kind: "running" };
    case "starting":
      return { label: "Starting", kind: "running" };
    case "pending":
      return { label: "Pending", kind: "queued" };
    case "failed":
      return { label: "Failed", kind: "failed" };
    case "error":
      return { label: "Error", kind: "failed" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getOpenApiConnectionDisplayStatus(
  status: string,
  toolCount: number
): string {
  const normalized = normalizeStatus(status);

  if (
    normalized === "connected" ||
    normalized === "running" ||
    normalized === "succeeded" ||
    toolCount > 0
  ) {
    return "connected";
  }

  if (normalized === "pending" || normalized === "starting") {
    return "starting";
  }

  if (normalized === "failed") {
    return "failed";
  }

  return normalized;
}

export function getTaskStatusPresentation(status: string): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "completed":
      return { label: "Completed", labelKey: "completed", kind: "done" };
    case "success":
      return { label: "Success", labelKey: "success", kind: "done" };
    case "running":
    // A2A's name for the same state.
    case "working":
    case "in_progress":
      return { label: "Running", labelKey: "running", kind: "running" };
    // Everything that waits on a person — an answer, an approval, a turn-limit
    // continuation, or lifting a budget/policy block — reads as one status;
    // the task itself says which.
    case "input_required":
    case "waiting_for_input":
    case "waiting_for_approval":
    case "waiting_for_continuation":
    case "blocked":
      return {
        label: "Needs action",
        labelKey: "needsAction",
        kind: "attention",
      };
    case "failed":
      return { label: "Failed", labelKey: "failed", kind: "failed" };
    case "error":
      return { label: "Error", labelKey: "error", kind: "failed" };
    case "cancelled":
    case "canceled":
      return { label: "Cancelled", labelKey: "cancelled", kind: "cancelled" };
    case "paused":
      return { label: "Paused", labelKey: "paused", kind: "paused" };
    // Accepted but not picked up by a worker yet. `submitted` is the status a
    // task is created with and `preparing` precedes its dispatch; A2A folds
    // both into SUBMITTED alongside `pending`, and so do we.
    case "pending":
    case "submitted":
    case "preparing":
      return { label: "Pending", labelKey: "pending", kind: "queued" };
    case "scheduled":
      return { label: "Scheduled", labelKey: "scheduled", kind: "scheduled" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getApiKeyStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "active":
      return { label: "Active", kind: "active" };
    case "expired":
      return { label: "Expired", kind: "off" };
    case "revoked":
      return { label: "Revoked", kind: "cancelled" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getTriggerStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "active":
      return { label: "Active", kind: "active" };
    case "inactive":
    case "disabled":
      return { label: "Inactive", kind: "off" };
    case "paused":
      return { label: "Paused", kind: "paused" };
    case "error":
    case "failed":
      return { label: "Error", kind: "failed" };
    default:
      return fallbackStatusPresentation(status);
  }
}

/**
 * What protects a webhook URL. Only "signed" is a healthy state: the other two
 * accept a request from anyone who knows the URL.
 */
export function getWebhookSigningPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "signed":
      return { label: "Signed", labelKey: "signed", kind: "active" };
    case "unsigned":
      return { label: "Unsigned", labelKey: "unsigned", kind: "attention" };
    case "unsupported":
      return {
        label: "Not verified",
        labelKey: "unsupported",
        kind: "attention",
      };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getTriggerExecutionStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "completed":
      return { label: "Completed", kind: "done" };
    case "success":
      return { label: "Success", kind: "done" };
    case "running":
    case "in_progress":
      return { label: "Running", kind: "running" };
    case "pending":
      return { label: "Pending", kind: "queued" };
    case "failed":
      return { label: "Failed", kind: "failed" };
    case "error":
      return { label: "Error", kind: "failed" };
    case "timeout":
      return { label: "Timed out", kind: "failed" };
    case "cancelled":
      return { label: "Cancelled", kind: "cancelled" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getAgentStatusPresentation(status: string): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "active":
      return { label: "Active", kind: "active" };
    case "running":
      return { label: "Running", kind: "running" };
    case "paused":
      return { label: "Paused", kind: "paused" };
    case "inactive":
    case "disabled":
      return { label: "Inactive", kind: "off" };
    case "error":
    case "failed":
      return { label: "Error", kind: "failed" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getPaymentStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "completed":
    case "success":
    case "paid":
    case "settled":
    case "confirmed":
      return { label: "Completed", kind: "done" };
    // Settlement in flight.
    case "pending":
    case "processing":
      return { label: "Pending", kind: "running" };
    case "failed":
    case "error":
      return { label: "Failed", kind: "failed" };
    case "cancelled":
    case "refunded":
      return { label: "Cancelled", kind: "cancelled" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getPolicyStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "enabled":
    case "active":
      return { label: "Enabled", kind: "active" };
    case "disabled":
    case "inactive":
      return { label: "Disabled", kind: "off" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getBillingStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "active":
      return { label: "Active", kind: "active" };
    case "trialing":
      return { label: "Trialing", kind: "active" };
    case "past_due":
      return { label: "Past due", kind: "attention" };
    case "canceled":
    case "cancelled":
      return { label: "Canceled", kind: "cancelled" };
    default:
      return fallbackStatusPresentation(status);
  }
}
