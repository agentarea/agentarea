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
  | "manual";

export interface TaskSource {
  kind: TaskSourceKind;
  label: string;
  detail?: string;
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
  const channelOrigin = getObject(parameters, "channel_origin");
  const channelType = channelOrigin && getString(channelOrigin, "type");

  if (channelOrigin && channelType === "telegram") {
    const detail =
      getString(channelOrigin, "chat_title") ||
      getString(channelOrigin, "username") ||
      getString(channelOrigin, "from") ||
      getString(channelOrigin, "chat_id");
    return { kind: "telegram", label: "Telegram", detail };
  }
  if (channelOrigin && channelType === "email") {
    const detail =
      getString(channelOrigin, "from") || getString(channelOrigin, "address");
    return { kind: "email", label: "Email", detail };
  }
  if (channelOrigin && channelType === "slack") {
    const detail =
      getString(channelOrigin, "channel_name") ||
      getString(channelOrigin, "channel_id");
    return { kind: "slack", label: "Slack", detail };
  }
  if (channelOrigin && channelType === "discord") {
    const detail =
      getString(channelOrigin, "channel_name") ||
      getString(channelOrigin, "channel_id");
    return { kind: "discord", label: "Discord", detail };
  }
  if (channelType) {
    return { kind: "channel", label: channelType };
  }

  const src = getString(parameters, "source");
  if (src === "agent_delegation") {
    const detail =
      getString(parameters, "delegating_agent") ||
      getString(parameters, "parent_agent") ||
      getString(parameters, "parent_agent_name");
    return { kind: "delegation", label: "Delegated", detail };
  }
  if (src === "a2a") {
    return { kind: "a2a", label: "A2A" };
  }

  const triggerType = getString(parameters, "trigger_type");
  const triggerName = getString(parameters, "trigger_name");
  if (triggerType === "cron") {
    return { kind: "schedule", label: "Scheduled", detail: triggerName };
  }
  if (triggerType === "webhook") {
    return { kind: "webhook", label: "Webhook", detail: triggerName };
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
