import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  createTriggerAction,
  listTriggerCatalogAction,
  updateTriggerAction,
} from "./actions";

const { createTrigger, updateTrigger, listTriggerCatalog, revalidatePath } =
  vi.hoisted(() => ({
    createTrigger: vi.fn(),
    updateTrigger: vi.fn(),
    listTriggerCatalog: vi.fn(),
    revalidatePath: vi.fn(),
  }));

vi.mock("@/lib/api", () => ({
  createTrigger,
  updateTrigger,
  listTriggerCatalog,
}));
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

  it("saves webhook methods, event filters and replacement credentials", async () => {
    await updateTriggerAction(
      { message: "" },
      form({
        trigger_type: "webhook",
        method_POST: "on",
        method_PATCH: "on",
        method_HEAD: "on",
        method_OPTIONS: "on",
        event_types: '["push"]',
        credential_signing_secret: "replacement",
        credential_unused: "",
      })
    );
    expect(updateTrigger).toHaveBeenCalledWith(
      triggerId,
      expect.objectContaining({
        allowed_methods: ["POST", "PATCH", "HEAD", "OPTIONS"],
        event_types: ["push"],
        channel_credentials: { signing_secret: "replacement" },
      })
    );
    expect(updateTrigger.mock.calls[0][1]).not.toHaveProperty(
      "cron_expression"
    );
  });

  it("clears event filters and preserves stored credentials when inputs are blank", async () => {
    await updateTriggerAction(
      { message: "" },
      form({
        trigger_type: "webhook",
        event_types: "[]",
        credential_bot_token: "",
        method_POST: "on",
      })
    );
    expect(updateTrigger.mock.calls[0][1]).toHaveProperty("event_types", []);
    expect(updateTrigger.mock.calls[0][1]).not.toHaveProperty(
      "channel_credentials"
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

  it("shows an unavailable secret error returned on create", async () => {
    createTrigger.mockResolvedValue({
      error: {
        detail:
          "Selected channel credential secret is not available in this workspace.",
      },
    });
    const result = await createTriggerAction(
      { message: "" },
      form({
        credential_secret_bot_token: "33333333-3333-4333-8333-333333333333",
      })
    );
    expect(result.errors?._form).toEqual([
      "API error: Selected channel credential secret is not available in this workspace.",
    ]);
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

  it.each(["create", "update"])(
    "sends secret references on %s without reading values",
    async (mode) => {
      const action =
        mode === "create" ? createTriggerAction : updateTriggerAction;
      const secretId = "33333333-3333-4333-8333-333333333333";
      const result = await action(
        { message: "" },
        form({
          trigger_type: "webhook",
          webhook_type: "telegram",
          credential_secret_bot_token: secretId,
        })
      );
      expect(result.success).toBe(true);
      const payload =
        mode === "create"
          ? createTrigger.mock.calls[0][0]
          : updateTrigger.mock.calls[0][1];
      expect(payload.channel_credentials).toEqual({
        bot_token: { secret_id: secretId },
      });
    }
  );

  it.each(["create", "update"])(
    "rejects invalid secret selections before %s",
    async (mode) => {
      const action =
        mode === "create" ? createTriggerAction : updateTriggerAction;
      const result = await action(
        { message: "" },
        form({ credential_secret_bot_token: "not-a-secret-id" })
      );
      expect(result.errors?.credential_secret_bot_token).toBeDefined();
      expect(createTrigger).not.toHaveBeenCalled();
      expect(updateTrigger).not.toHaveBeenCalled();
    }
  );

  it("keeps the catalog usable when one entry is of a kind this build cannot render", async () => {
    listTriggerCatalog.mockResolvedValue({
      data: [
        {
          id: "cron",
          name: "Cron",
          icon: "cron",
          description: "Run on a schedule",
          kind: "schedule",
          backend_type: "cron",
        },
        {
          id: "mailbox",
          name: "Mailbox (IMAP)",
          icon: "gmail",
          description: "Poll a mailbox",
          kind: "messaging",
          backend_type: "polling",
        },
        {
          id: "quantum",
          name: "Quantum",
          icon: "q",
          description: "From a newer server",
          kind: "telepathy",
          backend_type: "telepathy",
        },
      ],
    });

    const catalog = await listTriggerCatalogAction();

    expect(catalog.map((entry) => entry.id)).toEqual(["cron", "mailbox"]);
  });

  it("refuses to create an extracting channel with no secret picked", async () => {
    const result = await createTriggerAction(
      { message: "" },
      form({
        trigger_type: "webhook",
        webhook_type: "telegram",
        data_extractor: "telegram",
        credential_secret_bot_token: "",
      })
    );
    expect(result.errors?.credential_secret_bot_token).toEqual([
      "Select a workspace secret",
    ]);
    expect(createTrigger).not.toHaveBeenCalled();
  });

  it("leaves existing credentials untouched when no replacement secret is selected", async () => {
    await updateTriggerAction(
      { message: "" },
      form({ credential_secret_bot_token: "" })
    );
    expect(updateTrigger.mock.calls[0][1]).not.toHaveProperty(
      "channel_credentials"
    );
  });
});
