import type { StatusTone } from "@/lib/status";
import { readLastDispatch } from "./usage";

/**
 * One verdict per connection, built from the two facts the platform actually
 * records:
 *
 * - `verification` — a setup-time probe. It is written on create, on an
 *   explicit re-verify, and by the monitor sweep, which only picks up
 *   `never_attempted` docker/command rows. A `succeeded` verification is never
 *   refreshed, so on its own it says "this was configured correctly once".
 * - `last_dispatch` — the outcome of the last real tool call, written on every
 *   dispatch.
 *
 * Neither is liveness: MCP workloads start on demand and are reaped when idle,
 * so "connected" is not a state this product has.
 */
export type ConnectionStateKey =
  | "verifying"
  | "broken"
  | "failing"
  | "working"
  | "ready"
  | "unconfigured";

export interface ConnectionState {
  key: ConnectionStateKey;
  tone: StatusTone;
  pulse?: boolean;
  /** Timestamp of the signal this verdict came from, when known. */
  at: string | null;
}

const TONES: Record<ConnectionStateKey, { tone: StatusTone; pulse?: boolean }> = {
  verifying: { tone: "info", pulse: true },
  broken: { tone: "danger" },
  failing: { tone: "danger" },
  working: { tone: "success" },
  ready: { tone: "neutral" },
  unconfigured: { tone: "warning" },
};

function state(key: ConnectionStateKey, at: string | null): ConnectionState {
  return { key, at, ...TONES[key] };
}

interface VerificationLike {
  status?: string;
  at?: string | null;
}

export function getMcpConnectionState(instance: {
  verification?: unknown;
  last_dispatch?: unknown;
  tools?: unknown;
  json_spec?: Record<string, unknown> | null;
  toolCount: number;
}): ConnectionState {
  const verification = (instance.verification ?? null) as VerificationLike | null;
  const dispatch = readLastDispatch(instance.last_dispatch);
  const verifiedAt = verification?.at ?? null;

  if (verification?.status === "in_progress") {
    return state("verifying", verifiedAt);
  }

  const dispatchState = dispatch
    ? state(dispatch.status === "succeeded" ? "working" : "failing", dispatch.at)
    : null;

  if (verification?.status === "failed") {
    // Both signals exist and disagree: the newer one is the current truth. A
    // probe that failed after the last successful call means it is broken now;
    // a call that succeeded after a failed probe means the probe is stale.
    const dispatchIsNewer =
      dispatchState?.at && verifiedAt && dispatchState.at > verifiedAt;
    return dispatchIsNewer ? dispatchState : state("broken", verifiedAt);
  }

  if (dispatchState) return dispatchState;
  if (instance.toolCount > 0) return state("ready", verifiedAt);
  return state("unconfigured", verifiedAt);
}

/**
 * OpenAPI connections carry no dispatch record — their tools are called through
 * the same activity but the outcome is not persisted per connection, so the
 * verdict rests on the connection's own status.
 */
export function getOpenApiConnectionState(
  displayStatus: string,
  toolCount: number
): ConnectionState {
  switch (displayStatus) {
    case "pending":
    case "importing":
    case "in_progress":
      return state("verifying", null);
    case "error":
    case "failed":
      return state("broken", null);
    default:
      return toolCount > 0 ? state("ready", null) : state("unconfigured", null);
  }
}
