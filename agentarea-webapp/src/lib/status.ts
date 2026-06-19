export type StatusTone =
  | "success"
  | "warning"
  | "danger"
  | "info"
  | "neutral";

export type StatusIndicatorSize = "default" | "sm";

export type StatusPresentation = {
  label: string;
  labelKey?: string;
  tone: StatusTone;
  pulse?: boolean;
};

export function normalizeStatus(status: string): string {
  return status.trim().toLowerCase();
}

function fallbackStatusPresentation(
  status: string,
  tone: StatusTone = "neutral"
): StatusPresentation {
  return { label: status, tone };
}

export function getMcpVerificationStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "succeeded":
      return { label: "Verified", labelKey: "connected", tone: "success" };
    case "in_progress":
      return {
        label: "Verifying",
        labelKey: "starting",
        tone: "info",
        pulse: true,
      };
    case "failed":
      return { label: "Failed", labelKey: "error", tone: "danger" };
    case "never_attempted":
      return { label: "Not verified", labelKey: "setup", tone: "neutral" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getMcpHealthStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "connected":
      return { label: "Connected", labelKey: "connected", tone: "success" };
    case "healthy":
      return { label: "Healthy", tone: "success" };
    case "running":
      return {
        label: "Running",
        labelKey: "running",
        tone: "info",
        pulse: true,
      };
    case "starting":
    case "pending":
    case "in_progress":
      return {
        label: "Starting",
        labelKey: "starting",
        tone: "warning",
        pulse: true,
      };
    case "setup":
    case "unknown":
      return {
        label: "Setup",
        labelKey: "setup",
        tone: "warning",
        pulse: true,
      };
    case "unhealthy":
      return { label: "Unhealthy", labelKey: "error", tone: "danger" };
    case "error":
      return { label: "Error", labelKey: "error", tone: "danger" };
    case "failed":
      return { label: "Failed", labelKey: "error", tone: "danger" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getMcpRuntimeHealthStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "healthy":
      return { label: "Healthy", tone: "success" };
    case "unhealthy":
      return { label: "Unhealthy", tone: "danger" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getOpenApiConnectionStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "active":
      return { label: "Active", tone: "success" };
    case "connected":
      return { label: "Connected", tone: "success" };
    case "succeeded":
      return { label: "Succeeded", tone: "success" };
    case "running":
      return { label: "Running", tone: "info", pulse: true };
    case "starting":
      return { label: "Starting", tone: "warning", pulse: true };
    case "pending":
      return { label: "Pending", tone: "warning", pulse: true };
    case "failed":
      return { label: "Failed", tone: "danger" };
    case "error":
      return { label: "Error", tone: "danger" };
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

export function getMcpCatalogStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "active":
      return { label: "active", tone: "success" };
    case "connected":
      return { label: "connected", tone: "success" };
    case "available":
      return { label: "available", tone: "success" };
    case "running":
      return { label: "running", tone: "info", pulse: true };
    case "setup":
      return { label: "setup", tone: "warning", pulse: true };
    case "pending":
      return { label: "pending", tone: "warning", pulse: true };
    case "starting":
      return { label: "starting", tone: "warning", pulse: true };
    case "failed":
      return { label: "failed", tone: "danger" };
    case "error":
      return { label: "error", tone: "danger" };
    case "inactive":
      return { label: "inactive", tone: "neutral" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getTaskStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "completed":
      return { label: "Completed", labelKey: "completed", tone: "success" };
    case "success":
      return { label: "Success", labelKey: "success", tone: "success" };
    case "running":
    case "in_progress":
      return {
        label: "Running",
        labelKey: "running",
        tone: "info",
        pulse: true,
      };
    case "input_required":
      return {
        label: "Input Required",
        labelKey: "inputRequired",
        tone: "warning",
        pulse: true,
      };
    case "failed":
      return { label: "Failed", labelKey: "failed", tone: "danger" };
    case "error":
      return { label: "Error", labelKey: "error", tone: "danger" };
    case "blocked":
      return { label: "Blocked", labelKey: "blocked", tone: "neutral" };
    case "cancelled":
      return { label: "Cancelled", labelKey: "cancelled", tone: "neutral" };
    case "paused":
      return { label: "Paused", labelKey: "paused", tone: "neutral" };
    case "pending":
      return { label: "Pending", labelKey: "pending", tone: "warning" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getApiKeyStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "active":
      return { label: "Active", tone: "success" };
    case "expired":
      return { label: "Expired", tone: "warning" };
    case "revoked":
      return { label: "Revoked", tone: "danger" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getTriggerStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "active":
      return { label: "Active", tone: "success" };
    case "inactive":
    case "paused":
      return {
        label: status === "paused" ? "Paused" : "Inactive",
        tone: "neutral",
      };
    case "error":
      return { label: "Error", tone: "danger" };
    default:
      return fallbackStatusPresentation(status);
  }
}

export function getTriggerExecutionStatusPresentation(
  status: string
): StatusPresentation {
  switch (normalizeStatus(status)) {
    case "completed":
      return { label: "Completed", tone: "success" };
    case "success":
      return { label: "Success", tone: "success" };
    case "running":
    case "in_progress":
      return { label: "Running", tone: "info", pulse: true };
    case "pending":
      return { label: "Pending", tone: "warning", pulse: true };
    case "failed":
      return { label: "Failed", tone: "danger" };
    case "error":
      return { label: "Error", tone: "danger" };
    case "cancelled":
      return { label: "Cancelled", tone: "neutral" };
    default:
      return fallbackStatusPresentation(status);
  }
}
