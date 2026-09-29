import { describe, expect, it } from "vitest";
import type { AgentPresetResponse } from "@/api/client/types.gen";
import { preferredModelId, presetFormValues } from "./agentPreset";

const preset: AgentPresetResponse = {
  id: "support-desk",
  name: "Support desk",
  description: "Answers customers on Telegram",
  instruction: "Answer support questions for agentarea.ai customers.",
  preferred_models: ["claude-sonnet", "gpt-4o"],
  tools: [
    { type: "code", name: "agentarea/shell", settings: null },
    {
      type: "code",
      name: "agentarea/web",
      settings: { disabled_methods: ["fetch"], requires_user_confirmation: true },
    },
    { type: "mcp", name: "github", settings: { allowed_tools: null } },
    {
      type: "openapi",
      name: "crm",
      settings: { openapi_connection_id: "crm-id", allowed_tools: [] },
    },
  ],
  skills: [
    { id: "11111111-1111-4111-8111-111111111111", name: "triage", description: null },
  ],
  unavailable_skills: ["refunds"],
  triggers: [
    {
      name: "Telegram",
      trigger_type: "webhook",
      webhook_type: "telegram",
      task_parameters: { text: "" },
    },
  ],
};

describe("presetFormValues", () => {
  it("replaces instruction, tools, catalog skills and triggers with the preset's", () => {
    const values = presetFormValues(preset);

    expect(values.instruction).toBe(preset.instruction);
    expect(values.tools_config).toEqual({
      mcp_server_configs: [{ mcp_server_id: "github", allowed_tools: null }],
      builtin_tools: [
        {
          tool_name: "agentarea/shell",
          disabled_methods: {},
          requires_user_confirmation: false,
        },
        {
          tool_name: "agentarea/web",
          disabled_methods: { fetch: false },
          requires_user_confirmation: true,
        },
      ],
      openapi_configs: [
        {
          openapi_connection_id: "crm-id",
          allowed_tools: [],
          load_mode: undefined,
          requires_user_confirmation: false,
        },
      ],
      carried_tools: [],
    });
    expect(values.skills).toEqual([
      {
        id: "11111111-1111-4111-8111-111111111111",
        name: "triage",
        description: null,
      },
    ]);
    expect(values.triggers).toEqual(preset.triggers);
    expect(values.triggers[0]).not.toBe(preset.triggers[0]);
  });

  it("clears tools, skills and triggers for Empty but keeps the instruction", () => {
    const values = presetFormValues(null);

    expect(values).toEqual({
      tools_config: {
        mcp_server_configs: [],
        builtin_tools: [],
        openapi_configs: [],
        carried_tools: [],
      },
      skills: [],
      triggers: [],
    });
    expect("instruction" in values).toBe(false);
  });
});

describe("preferredModelId", () => {
  const instances = [
    { id: "gpt", model_name: "openai/gpt-4o", is_active: true },
    { id: "sonnet-off", model_name: "anthropic/claude-sonnet-4", is_active: false },
  ];

  it("picks the first preference an active workspace model satisfies", () => {
    expect(preferredModelId(preset, instances)).toBe("gpt");
  });

  it("returns null when nothing matches", () => {
    expect(preferredModelId({ preferred_models: ["o3"] }, instances)).toBeNull();
    expect(preferredModelId({}, instances)).toBeNull();
  });
});
