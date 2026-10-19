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
      trigger_type: "stream",
      trigger_name: "Support inbox",
      source_type: "chat_bot",
    }),
    {
      kind: "event",
      label: "Event",
      detail: "Support inbox",
      sourceType: "chat_bot",
    },
    "stream event carries its catalog slug for the catalog to name"
  );

  // Provider-specific parameters are not read: which providers exist is the
  // catalog's business, and only source_type points into it.
  assertEqual(
    getTaskSource({
      channel_origin: { type: "chat_bot", chat_id: "1" },
      webhook_type: "repo_host",
    }),
    { kind: "manual", label: "Manual" },
    "channel_origin and webhook_type name nothing"
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
    { kind: "schedule", label: "Scheduled", detail: "Daily summary" },
    "cron trigger"
  );

  assertEqual(
    getTaskSource({ trigger_name: "Custom" }),
    { kind: "trigger", label: "Trigger", detail: "Custom" },
    "named trigger without type"
  );

  // A person pressed "run now". The schedule did not come due, so saying
  // "Scheduled" would be a plain lie about what happened.
  assertEqual(
    getTaskSource({
      trigger_type: "cron",
      trigger_name: "Daily summary",
      fired_by: "user-42",
    }),
    {
      kind: "manual_run",
      label: "Manual run",
      detail: "Daily summary",
      principalId: "user-42",
    },
    "manual run of a cron trigger"
  );

  assertEqual(
    getTaskSource({
      trigger_type: "stream",
      trigger_name: "Support inbox",
      source_type: "chat_bot",
      fired_by: "user-42",
    }),
    {
      kind: "manual_run",
      label: "Manual run",
      detail: "Support inbox",
      principalId: "user-42",
    },
    "manual run of a stream trigger drops the source it did not come from"
  );
});
