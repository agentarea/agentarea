import { describe, expect, it } from "vitest";
import { getTaskSource } from "../taskSource";

function assertEqual<T>(actual: T, expected: T, name: string) {
  it(name, () => {
    expect(actual).toEqual(expected);
  });
}

describe("getTaskSource", () => {
  assertEqual(
    getTaskSource(undefined),
    { kind: "manual", label: "Manual" },
    "undefined → manual"
  );
  assertEqual(
    getTaskSource(null),
    { kind: "manual", label: "Manual" },
    "null → manual"
  );
  assertEqual(
    getTaskSource({}),
    { kind: "manual", label: "Manual" },
    "empty → manual"
  );

  assertEqual(
    getTaskSource({
      channel_origin: {
        type: "telegram",
        chat_id: "123",
        chat_title: "Team chat",
      },
    }),
    {
      kind: "telegram",
      label: "Telegram",
      detail: "Team chat",
      channel: "telegram",
    },
    "telegram with chat_title"
  );

  assertEqual(
    getTaskSource({ channel_origin: { type: "telegram", chat_id: "123" } }),
    { kind: "telegram", label: "Telegram", detail: "123", channel: "telegram" },
    "telegram falls back to chat_id"
  );

  assertEqual(
    getTaskSource({
      channel_origin: { type: "email", from: "user@example.com" },
    }),
    {
      kind: "email",
      label: "Email",
      detail: "user@example.com",
      channel: "email",
    },
    "email with from"
  );

  assertEqual(
    getTaskSource({
      channel_origin: { type: "slack", channel_name: "#general" },
    }),
    { kind: "slack", label: "Slack", detail: "#general", channel: "slack" },
    "slack with channel_name"
  );

  assertEqual(
    getTaskSource({
      channel_origin: { type: "discord", channel_name: "general" },
    }),
    {
      kind: "discord",
      label: "Discord",
      detail: "general",
      channel: "discord",
    },
    "discord channel"
  );

  assertEqual(
    getTaskSource({ channel_origin: { type: "whatsapp" } }),
    { kind: "channel", label: "whatsapp", channel: "whatsapp" },
    "unknown channel falls through"
  );

  // The key the delegation activity actually writes. This test used to supply
  // `delegating_agent` — a display string nobody has ever written — and so
  // passed while the badge could never name the delegating agent.
  assertEqual(
    getTaskSource({
      source: "agent_delegation",
      parent_agent_id: "391de587-1c93-4f5a-9f97-98beabe101f4",
      parent_task_id: "b2c3d4e5-0000-0000-0000-000000000000",
    }),
    {
      kind: "delegation",
      label: "Delegated",
      principalId: "391de587-1c93-4f5a-9f97-98beabe101f4",
    },
    "agent delegation carries the parent agent id for the caller to resolve"
  );

  assertEqual(
    getTaskSource({ source: "agent_delegation" }),
    { kind: "delegation", label: "Delegated", principalId: undefined },
    "delegation without a parent id is still a delegation"
  );

  assertEqual(
    getTaskSource({ source: "a2a" }),
    { kind: "a2a", label: "A2A" },
    "a2a source"
  );

  assertEqual(
    getTaskSource({ trigger_type: "cron", trigger_name: "Daily summary" }),
    {
      kind: "schedule",
      label: "Scheduled",
      detail: "Daily summary",
      channel: "cron",
    },
    "cron trigger"
  );

  assertEqual(
    getTaskSource({ trigger_type: "webhook", trigger_name: "GitHub PR" }),
    {
      kind: "webhook",
      label: "Webhook",
      detail: "GitHub PR",
      channel: undefined,
    },
    "webhook trigger"
  );

  assertEqual(
    getTaskSource({
      trigger_type: "webhook",
      trigger_name: "PR opened",
      webhook_type: "github",
    }),
    {
      kind: "webhook",
      label: "Webhook",
      detail: "PR opened",
      channel: "github",
    },
    "webhook carries its channel for the catalog to name"
  );

  assertEqual(
    getTaskSource({ trigger_name: "Custom" }),
    { kind: "trigger", label: "Trigger", detail: "Custom" },
    "named trigger without type"
  );

  // channel_origin takes priority over trigger_*
  assertEqual(
    getTaskSource({
      channel_origin: { type: "telegram", chat_id: "1" },
      trigger_type: "webhook",
      trigger_name: "X",
    }),
    { kind: "telegram", label: "Telegram", detail: "1", channel: "telegram" },
    "channel_origin wins over trigger"
  );
});
