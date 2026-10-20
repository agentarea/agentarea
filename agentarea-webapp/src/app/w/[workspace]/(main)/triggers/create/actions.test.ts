import { beforeEach, describe, expect, it, vi } from "vitest";
import { createTriggerAction, updateTriggerAction } from "./actions";

const { createTrigger, updateTrigger, revalidatePath } = vi.hoisted(() => ({
  createTrigger: vi.fn(),
  updateTrigger: vi.fn(),
  revalidatePath: vi.fn(),
}));

vi.mock("@/lib/api", () => ({ createTrigger, updateTrigger }));
vi.mock("next/cache", () => ({ revalidatePath }));
vi.mock("@/lib/workspace-request", () => ({
  requestWorkspacePath: async (path: string) => `/w/acme${path}`,
}));

const agentId = "11111111-1111-4111-8111-111111111111";
const triggerId = "22222222-2222-4222-8222-222222222222";

function form(overrides: Record<string, string> = {}) {
  const data = new FormData();
  for (const [key, value] of Object.entries({
    id: triggerId,
    name: "Updated daily report",
    description: "Send the report to the team",
    agent_id: agentId,
    trigger_type: "cron",
    cron_expression: "17 14 * * 1-5",
    timezone: "Europe/Moscow",
    task_parameters: JSON.stringify({ text: "Summarize yesterday", budget: 2 }),
    failure_threshold: "3",
    ...overrides,
  })) {
    data.set(key, value);
  }
  return data;
}

describe("trigger form actions", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    createTrigger.mockResolvedValue({ data: { id: triggerId } });
    updateTrigger.mockResolvedValue({ data: { id: triggerId } });
  });

  it("saves every editable cron field and refreshes the list and detail", async () => {
    const result = await updateTriggerAction({ message: "" }, form());

    expect(result.success).toBe(true);
    expect(updateTrigger).toHaveBeenCalledWith(triggerId, {
      name: "Updated daily report",
      description: "Send the report to the team",
      agent_id: agentId,
      cron_expression: "17 14 * * 1-5",
      timezone: "Europe/Moscow",
      task_parameters: { text: "Summarize yesterday", budget: 2 },
      failure_threshold: 3,
    });
    expect(revalidatePath).toHaveBeenCalledWith("/w/acme/triggers");
    expect(revalidatePath).toHaveBeenCalledWith(
      `/w/acme/triggers/${triggerId}`
    );
  });

  it("allows clearing descriptions and all task parameters", async () => {
    await updateTriggerAction(
      { message: "" },
      form({ description: "", task_parameters: "{}" })
    );
    expect(updateTrigger).toHaveBeenCalledWith(
      triggerId,
      expect.objectContaining({
        description: "",
        task_parameters: {},
      })
    );
  });

  it("saves a stream trigger's session setting", async () => {
    await updateTriggerAction(
      { message: "" },
      form({
        trigger_type: "stream",
        session_continue: "false",
        session_idle_timeout: "1h",
      })
    );
    expect(updateTrigger.mock.calls[0][1]).toHaveProperty("session", {
      continue: false,
      idle_timeout: "1h",
    });
    expect(updateTrigger.mock.calls[0][1]).not.toHaveProperty(
      "cron_expression"
    );
  });

  it.each([
    ["name", ""],
    ["agent_id", "not-a-uuid"],
    ["failure_threshold", "101"],
    ["failure_threshold", "0"],
    ["failure_threshold", "2.5"],
    ["task_parameters", "[]"],
  ])("rejects invalid %s before sending the update", async (field, value) => {
    const result = await updateTriggerAction(
      { message: "" },
      form({ [field]: value })
    );
    expect(result.errors?.[field]).toBeDefined();
    expect(updateTrigger).not.toHaveBeenCalled();
  });

  it("shows the backend error detail", async () => {
    updateTrigger.mockResolvedValue({
      error: { detail: "Invalid cron expression" },
    });
    const result = await updateTriggerAction({ message: "" }, form());
    expect(result.errors?._form).toEqual([
      "API error: Invalid cron expression",
    ]);
    expect(revalidatePath).not.toHaveBeenCalled();
  });

  it("creates a stream trigger bound to the chosen stream", async () => {
    const streamId = "44444444-4444-4444-8444-444444444444";
    const result = await createTriggerAction(
      { message: "" },
      form({
        trigger_type: "stream",
        stream_id: streamId,
        session_continue: "true",
        session_idle_timeout: "30m",
      })
    );
    expect(result.success).toBe(true);
    expect(createTrigger).toHaveBeenCalledWith(
      expect.objectContaining({
        trigger_type: "stream",
        stream_id: streamId,
        session: { continue: true, idle_timeout: "30m" },
      })
    );
  });

  it("includes the description when creating through the shared form", async () => {
    const result = await createTriggerAction({ message: "" }, form());
    expect(result.success).toBe(true);
    expect(createTrigger).toHaveBeenCalledWith(
      expect.objectContaining({
        description: "Send the report to the team",
      })
    );
  });
});
