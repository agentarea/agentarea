import { describe, expect, it } from "vitest";
import type { InstallResult } from "@/api/client/types.gen";
import { launchPlan, type InstallDraft } from "../bundle-plan";

function request(
  channels: { key: string; enabled: boolean }[] = [],
  automations: { key: string; enabled: boolean }[] = []
): InstallDraft {
  return {
    bundle: {
      name: "b",
      channels: channels.map((c) => ({
        ...c,
        type: "telegram",
        name: `${c.key} bot`,
        agent: "a",
      })),
      automations: automations.map((a) => ({
        ...a,
        cron: "0 9 * * 1",
        agent: "a",
        prompt: `run ${a.key}`,
      })),
    },
    setup_values: {},
  };
}

function result(entities: InstallResult["entities"]): InstallResult {
  return { bundle_name: "b", entities };
}

describe("launchPlan", () => {
  it("opens the chat of a lone agent with nothing left to do", () => {
    const plan = launchPlan(
      request(),
      result([
        { kind: "agent", key: "a", name: "A", action: "created", id: "1" },
        { kind: "skill", key: "s", name: "S", action: "created", id: "2" },
      ])
    );
    expect(plan.openNow).toBe("/agents/1/new-task");
    expect(plan.todo).toEqual([]);
  });

  it("keeps an organisation of several agents on the launch screen", () => {
    const plan = launchPlan(
      request(),
      result([
        { kind: "agent", key: "a", name: "A", action: "created", id: "1" },
        { kind: "agent", key: "b", name: "B", action: "reused", id: "2" },
      ])
    );
    expect(plan.openNow).toBeNull();
    expect(plan.agents.map((a) => a.href)).toEqual([
      "/agents/1/new-task",
      "/agents/2/new-task",
    ]);
  });

  it("lists channels and schedules this install left off, linked to their trigger", () => {
    const plan = launchPlan(
      request(
        [{ key: "tg", enabled: false }],
        [
          { key: "daily", enabled: false },
          { key: "weekly", enabled: true },
        ]
      ),
      result([
        { kind: "agent", key: "a", name: "A", action: "created", id: "1" },
        {
          kind: "channel",
          key: "tg",
          name: "b:tg",
          action: "created",
          id: "t1",
        },
        {
          kind: "automation",
          key: "daily",
          name: "b:daily",
          action: "created",
          id: "t2",
        },
        {
          kind: "automation",
          key: "weekly",
          name: "b:weekly",
          action: "created",
          id: "t3",
        },
      ])
    );
    expect(plan.todo.map((t) => [t.name, t.href])).toEqual([
      ["tg bot", "/triggers/t1"],
      ["run daily", "/triggers/t2"],
    ]);
    expect(plan.openNow).toBeNull();
  });

  it("does not judge a reused trigger by the request, which did not set it", () => {
    const plan = launchPlan(
      request([{ key: "tg", enabled: false }]),
      result([
        { kind: "agent", key: "a", name: "A", action: "created", id: "1" },
        // The backend returns a reused trigger without an id.
        { kind: "channel", key: "tg", name: "b:tg", action: "reused" },
      ])
    );
    expect(plan.todo).toEqual([]);
    expect(plan.openNow).toBe("/agents/1/new-task");
  });

  it("opens the chat of the agent a redeploy kept, not one the bundle dropped", () => {
    const plan = launchPlan(
      request(),
      result([
        { kind: "agent", key: "a", name: "A", action: "updated", id: "1" },
        { kind: "agent", key: "old", name: "Old", action: "orphaned", id: "2" },
        { kind: "mcp", key: "m", name: "Mail", action: "orphaned", id: "c1" },
      ])
    );
    expect(plan.agents.map((a) => a.id)).toEqual(["1"]);
    expect(plan.connections).toEqual([]);
    expect(plan.openNow).toBe("/agents/1/new-task");
  });

  it("reports what was skipped and links connections to their page", () => {
    const plan = launchPlan(
      request(),
      result([
        { kind: "agent", key: "a", name: "A", action: "created", id: "1" },
        { kind: "mcp", key: "m", name: "Mail", action: "created", id: "c1" },
        {
          kind: "skill",
          key: "s",
          name: "S",
          action: "skipped",
          detail: "source_type 'github' install not yet supported",
        },
      ])
    );
    expect(plan.connections).toEqual([
      { key: "m", id: "c1", name: "Mail", href: "/connections/c1" },
    ]);
    expect(plan.todo).toEqual([]);
    expect(plan.skipped).toEqual([
      {
        key: "skill:s",
        kind: "skill",
        name: "S",
        detail: "source_type 'github' install not yet supported",
      },
    ]);
    expect(plan.openNow).toBeNull();
  });
});
