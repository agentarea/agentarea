import type { StatusPresentation, StatusResolver } from "./types";

export function createStatusPresentation(
  label: string,
  tone: StatusPresentation["tone"],
  options?: { pulse?: boolean }
): StatusPresentation {
  return {
    label,
    tone,
    pulse: options?.pulse,
  };
}

export function normalizeStatus(status: string): string {
  return status.trim().toLowerCase();
}

export function createStatusResolver(
  statuses: Record<string, StatusPresentation>,
  fallback: StatusResolver
): StatusResolver {
  return (status: string) => {
    const normalized = normalizeStatus(status);
    return statuses[normalized] ?? fallback(status);
  };
}

export function createPassthroughStatusPresentation(
  status: string,
  tone: StatusPresentation["tone"] = "neutral"
): StatusPresentation {
  return createStatusPresentation(status, tone);
}
