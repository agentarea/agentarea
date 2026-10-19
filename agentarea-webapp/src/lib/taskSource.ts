export type TaskSourceKind =
  | "event"
  | "delegation"
  | "schedule"
  | "trigger"
  | "a2a"
  | "manual_run"
  | "manual";

export interface TaskSource {
  kind: TaskSourceKind;
  label: string;
  detail?: string;
  /**
   * The catalog slug of the event that started the task (`source_type`). An
   * open set: the name and icon come from the source-types catalog, never from
   * matching on this here.
   */
  sourceType?: string;
  /**
   * A principal id the caller should resolve into a name via GET /v1/principals
   * — the delegating agent, for a task another agent started. Deliberately an
   * id and not a name: parameters record how a task was created, and a name
   * written there would be frozen at creation while the same screen renders
   * every other agent's live name.
   */
  principalId?: string;
}

type Params = Record<string, unknown> | null | undefined;

function getString(obj: unknown, key: string): string | undefined {
  if (obj && typeof obj === "object" && key in (obj as Record<string, unknown>)) {
    const v = (obj as Record<string, unknown>)[key];
    return typeof v === "string" && v.length > 0 ? v : undefined;
  }
  return undefined;
}

export function getTaskSource(parameters: Params): TaskSource {
  // Someone pressed "run now" on a trigger. The backend writes fired_by on that
  // path and nowhere else, so it settles what caused this run before anything
  // else gets a say — including source_type, which a manual run of a stream
  // trigger may still carry. Where the answer goes is not what started it. The
  // trigger is still named: which one was run is the next question.
  const firedBy = getString(parameters, "fired_by");
  if (firedBy) {
    return {
      kind: "manual_run",
      label: "Manual run",
      detail: getString(parameters, "trigger_name"),
      principalId: firedBy,
    };
  }

  // A stream trigger fired on an event: the catalog entry it came through
  // names the provider.
  const sourceType = getString(parameters, "source_type");
  if (sourceType) {
    return {
      kind: "event",
      label: "Event",
      detail: getString(parameters, "trigger_name"),
      sourceType,
    };
  }

  const src = getString(parameters, "source");
  if (src === "agent_delegation") {
    // `parent_agent_id` is the only key the delegation activity actually writes.
    // This used to look for delegating_agent / parent_agent / parent_agent_name
    // — three display strings nobody has ever written — so the badge could never
    // name the agent that delegated.
    return {
      kind: "delegation",
      label: "Delegated",
      principalId: getString(parameters, "parent_agent_id"),
    };
  }
  if (src === "a2a") {
    return { kind: "a2a", label: "A2A" };
  }

  const triggerType = getString(parameters, "trigger_type");
  const triggerName = getString(parameters, "trigger_name");

  if (triggerType === "cron") {
    return { kind: "schedule", label: "Scheduled", detail: triggerName };
  }
  if (triggerName || triggerType) {
    return {
      kind: "trigger",
      label: "Trigger",
      detail: triggerName || triggerType,
    };
  }

  return { kind: "manual", label: "Manual" };
}
