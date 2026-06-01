/**
 * Tests for getTaskSource (pure function).
 * Run with: npx tsx src/lib/__tests__/taskSource.test.ts
 */
import { getTaskSource } from "../taskSource";

let failed = 0;
function assertEqual<T>(actual: T, expected: T, name: string) {
  const ok = JSON.stringify(actual) === JSON.stringify(expected);
  if (!ok) {
    failed += 1;
    console.error(
      `FAIL ${name}\n  expected: ${JSON.stringify(expected)}\n  actual:   ${JSON.stringify(actual)}`,
    );
  } else {
    console.log(`PASS ${name}`);
  }
}

assertEqual(getTaskSource(undefined), { kind: "manual", label: "Manual" }, "undefined → manual");
assertEqual(getTaskSource(null), { kind: "manual", label: "Manual" }, "null → manual");
assertEqual(getTaskSource({}), { kind: "manual", label: "Manual" }, "empty → manual");

assertEqual(
  getTaskSource({
    channel_origin: { type: "telegram", chat_id: "123", chat_title: "Team chat" },
  }),
  { kind: "telegram", label: "Telegram", detail: "Team chat" },
  "telegram with chat_title",
);

assertEqual(
  getTaskSource({ channel_origin: { type: "telegram", chat_id: "123" } }),
  { kind: "telegram", label: "Telegram", detail: "123" },
  "telegram falls back to chat_id",
);

assertEqual(
  getTaskSource({ channel_origin: { type: "email", from: "user@example.com" } }),
  { kind: "email", label: "Email", detail: "user@example.com" },
  "email with from",
);

assertEqual(
  getTaskSource({ channel_origin: { type: "slack", channel_name: "#general" } }),
  { kind: "slack", label: "Slack", detail: "#general" },
  "slack with channel_name",
);

assertEqual(
  getTaskSource({ channel_origin: { type: "discord", channel_name: "general" } }),
  { kind: "discord", label: "Discord", detail: "general" },
  "discord channel",
);

assertEqual(
  getTaskSource({ channel_origin: { type: "whatsapp" } }),
  { kind: "channel", label: "whatsapp" },
  "unknown channel falls through",
);

assertEqual(
  getTaskSource({ source: "agent_delegation", delegating_agent: "Researcher" }),
  { kind: "delegation", label: "Delegated", detail: "Researcher" },
  "agent delegation",
);

assertEqual(
  getTaskSource({ source: "a2a" }),
  { kind: "a2a", label: "A2A" },
  "a2a source",
);

assertEqual(
  getTaskSource({ trigger_type: "cron", trigger_name: "Daily summary" }),
  { kind: "schedule", label: "Scheduled", detail: "Daily summary" },
  "cron trigger",
);

assertEqual(
  getTaskSource({ trigger_type: "webhook", trigger_name: "GitHub PR" }),
  { kind: "webhook", label: "Webhook", detail: "GitHub PR" },
  "webhook trigger",
);

assertEqual(
  getTaskSource({ trigger_name: "Custom" }),
  { kind: "trigger", label: "Trigger", detail: "Custom" },
  "named trigger without type",
);

// channel_origin takes priority over trigger_*
assertEqual(
  getTaskSource({
    channel_origin: { type: "telegram", chat_id: "1" },
    trigger_type: "webhook",
    trigger_name: "X",
  }),
  { kind: "telegram", label: "Telegram", detail: "1" },
  "channel_origin wins over trigger",
);

if (failed > 0) {
  console.error(`\n${failed} test(s) failed`);
  process.exit(1);
} else {
  console.log("\nAll tests passed");
}
