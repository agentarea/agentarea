export type TaskSourceKind =
  | "telegram"
  | "email"
  | "slack"
  | "discord"
  | "channel"
  | "delegation"
  | "schedule"
  | "webhook"
  | "trigger"
  | "a2a"
  | "manual_run"
  | "manual";

export interface TaskSource {
  kind: TaskSourceKind;
  label: string;
  detail?: string;
  /**
   * The channel id as the backend spells it (`webhook_type`). Open set — new
   * channels arrive by configuration, so resolve the name and icon through the
   * trigger catalog rather than matching on this here.
   */
  channel?: string;
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

function getObject(obj: unknown, key: string): Record<string, unknown> | undefined {
  if (obj && typeof obj === "object" && key in (obj as Record<string, unknown>)) {
    const v = (obj as Record<string, unknown>)[key];
    return v && typeof v === "object" ? (v as Record<string, unknown>) : undefined;
  }
  return undefined;
}

export function getTaskSource(parameters: Params): TaskSource {
  // Someone pressed "run now" on a trigger. The backend writes fired_by on that
  // path and nowhere else, so it settles what caused this run before anything
  // else gets a say — including channel_origin, which a manual run of a channel
  // trigger still carries because the reply routes back to that chat. Where the
  // answer goes is not what started it. The trigger is still named: which one
  // was run is the next question.
  const firedBy = getString(parameters, "fired_by");
  if (firedBy) {
    return {
      kind: "manual_run",
      label: "Manual run",
      detail: getString(parameters, "trigger_name"),
      principalId: firedBy,
    };
  }

  const channelOrigin = getObject(parameters, "channel_origin");
  const channelType = channelOrigin && getString(channelOrigin, "type");

  if (channelOrigin && channelType === "telegram") {
    const detail =
      getString(channelOrigin, "chat_title") ||
      getString(channelOrigin, "username") ||
      getString(channelOrigin, "from") ||
      getString(channelOrigin, "chat_id");
    return { kind: "telegram", label: "Telegram", detail, channel: "telegram" };
  }
  if (channelOrigin && channelType === "email") {
    const detail =
      getString(channelOrigin, "from") || getString(channelOrigin, "address");
    return { kind: "email", label: "Email", detail, channel: "email" };
  }
  if (channelOrigin && channelType === "slack") {
    const detail =
      getString(channelOrigin, "channel_name") ||
      getString(channelOrigin, "channel_id");
    return { kind: "slack", label: "Slack", detail, channel: "slack" };
  }
  if (channelOrigin && channelType === "discord") {
    const detail =
      getString(channelOrigin, "channel_name") ||
      getString(channelOrigin, "channel_id");
    return { kind: "discord", label: "Discord", detail, channel: "discord" };
  }
  if (channelType) {
    return { kind: "channel", label: channelType, channel: channelType };
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
    return {
      kind: "schedule",
      label: "Scheduled",
      detail: triggerName,
      channel: "cron",
    };
  }
  if (triggerType === "webhook") {
    // The channel goes out raw: which channels exist is the catalog's business
    // (GET /v1/triggers/catalog), not this module's. channel_origin above only
    // covers the channels we route replies back to.
    return {
      kind: "webhook",
      label: "Webhook",
      detail: triggerName,
      channel: getString(parameters, "webhook_type"),
    };
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
