"use server";

import { z } from "zod";
import type { components } from "@/api/schema";
import { createAgent } from "@/lib/api";

// Define Zod schema for MCP Tool Config
const MCPToolConfigSchema = z.object({
  tool_name: z.string().min(1, "Tool name is required"),
  requires_user_confirmation: z.boolean().optional().default(false),
});

// Define Zod schema for MCPConfig to validate tools_config array
const MCPConfigSchema = z.object({
  mcp_server_id: z.string().uuid("Invalid MCP Server ID"),
  allowed_tools: z.array(MCPToolConfigSchema).optional().nullable(),
});

// Define Zod schema for Builtin Tool Config
const BuiltinToolConfigSchema = z.object({
  tool_name: z.string().min(1, "Builtin tool name is required"),
  requires_user_confirmation: z.boolean().optional().default(false),
  enabled: z.boolean().optional().default(true),
  disabled_methods: z.record(z.boolean()).optional(),
});

// Define Zod schema for individual Event Config items
const EventConfigItemSchema = z.object({
  event_type: z.string().min(1, "Event type is required"), // e.g., 'text_input', 'cron'
  config: z.record(z.unknown()).optional().nullable(), // For future event-specific configs
  enabled: z.boolean().default(true), // Whether the event is enabled - always boolean
});

// Extended type for form state that includes the instruction field
export interface AddAgentFormState {
  message: string;
  errors?: { [key: string]: string[] };
  fieldValues?: {
    name?: string;
    description?: string;
    instruction?: string;
    model_id?: string;
    tools_config?: {
      mcp_server_configs?: Array<{
        mcp_server_id: string;
        allowed_tools?: Array<{
          tool_name: string;
          requires_user_confirmation?: boolean;
        }> | null;
      }> | null;
      builtin_tools?: Array<{
        tool_name: string;
        requires_user_confirmation?: boolean;
        enabled?: boolean;
        disabled_methods?: Record<string, boolean>;
      }> | null;
    } | null;
    events_config?: {
      events?: Array<{
        event_type: string;
        config?: Record<string, unknown> | null;
        enabled?: boolean;
      }> | null;
    } | null;
    planning?: boolean;
    id?: string;
  };
  // Field-specific errors
  name?: string[];
  description?: string[];
  instruction?: string[];
  model_id?: string[];
  "events_config.events"?: string[];
  "tools_config.mcp_server_configs"?: string[];
  planning?: string[];
  _form?: string[];
}

const AgentSchema = z.object({
  name: z.string().min(1, "Agent name is required"),
  description: z.string().optional(),
  instruction: z.string().min(1, "Instruction is required"),
  model_id: z.string().min(1, "Model is required"),
  tools_config: z
    .object({
      mcp_server_configs: z.array(MCPConfigSchema).optional().nullable(),
      builtin_tools: z.array(BuiltinToolConfigSchema).optional().nullable(),
    })
    .optional()
    .nullable(),
  events_config: z
    .object({
      // Expect an array of EventConfigItemSchema objects
      events: z.array(EventConfigItemSchema).optional().nullable(),
    })
    .optional()
    .nullable(),
  planning: z.boolean().optional(),
});

export async function addAgent(
  prevState: AddAgentFormState,
  formData: FormData
): Promise<AddAgentFormState> {
  // Need to manually reconstruct the array/object structure for validation
  const mcpConfigs: Record<
    number,
    Partial<components["schemas"]["MCPConfig"]>
  > = {};
  const mcpToolConfigs: Record<
    number,
    Record<number, Partial<components["schemas"]["MCPToolConfig"]>>
  > = {};
  type BuiltinToolConfigMutable = {
    tool_name?: string;
    requires_user_confirmation?: boolean;
    enabled?: boolean;
    disabled_methods?: Record<string, boolean>;
  };
  const builtinToolConfigs: Record<number, BuiltinToolConfigMutable> = {};

  formData.forEach((value, key) => {
    // Handle MCP server configs
    const mcpMatch = key.match(
      /tools_config\.mcp_server_configs\[(\d+)\]\.mcp_server_id/
    );
    if (mcpMatch) {
      const index = parseInt(mcpMatch[1], 10);
      if (!mcpConfigs[index]) {
        mcpConfigs[index] = {};
      }
      mcpConfigs[index].mcp_server_id = value as string;
    }

    // Handle allowed tools
    const toolMatch = key.match(
      /tools_config\.mcp_server_configs\[(\d+)\]\.allowed_tools\[(\d+)\]\.\(.*\)/
    );
    if (toolMatch) {
      const serverIndex = parseInt(toolMatch[1], 10);
      const toolIndex = parseInt(toolMatch[2], 10);
      const field =
        toolMatch[3] as keyof components["schemas"]["MCPToolConfig"];

      if (!mcpToolConfigs[serverIndex]) {
        mcpToolConfigs[serverIndex] = {};
      }
      if (!mcpToolConfigs[serverIndex][toolIndex]) {
        mcpToolConfigs[serverIndex][toolIndex] = {};
      }

      if (field === "requires_user_confirmation") {
        mcpToolConfigs[serverIndex][toolIndex][field] =
          value === "on" || value === "true";
      } else if (field === "tool_name") {
        mcpToolConfigs[serverIndex][toolIndex][field] = value as string;
      } else {
        (mcpToolConfigs[serverIndex][toolIndex] as any)[field] =
          value as unknown;
      }
    }

    // Handle builtin tools
    const builtinMatch = key.match(
      /tools_config\.builtin_tools\[(\d+)\]\.([^\]]+)/
    );
    if (builtinMatch) {
      const index = parseInt(builtinMatch[1], 10);
      const field = builtinMatch[2] as keyof BuiltinToolConfigMutable;

      if (!builtinToolConfigs[index]) {
        builtinToolConfigs[index] = {};
      }

      switch (field) {
        case "requires_user_confirmation":
        case "enabled":
          builtinToolConfigs[index][field] = value === "on" || value === "true";
          break;
        case "disabled_methods":
          try {
            const parsed = JSON.parse(value as string) as Record<
              string,
              boolean
            >;
            builtinToolConfigs[index].disabled_methods = parsed;
          } catch (parseError) {
            console.error(
              `Failed to parse disabled_methods JSON for builtin tool ${index}:`,
              parseError
            );
            builtinToolConfigs[index].disabled_methods = {};
          }
          break;
        case "tool_name":
          builtinToolConfigs[index].tool_name = value as string;
          break;
        default:
          break;
      }
    }
  });

  // Combine MCP configs with their allowed tools
  Object.keys(mcpConfigs).forEach((serverIndexStr) => {
    const serverIndex = parseInt(serverIndexStr, 10);
    if (mcpToolConfigs[serverIndex]) {
      mcpConfigs[serverIndex].allowed_tools = Object.values(
        mcpToolConfigs[serverIndex]
      ) as components["schemas"]["MCPToolConfig"][];
    }
  });
  // Convert the record back to an array, ensuring required fields are present or handled by Zod
  const mcpConfigsArray = Object.values(mcpConfigs).map(
    (config) => config as components["schemas"]["MCPConfig"]
  );

  // Convert builtin tools record to array
  const builtinToolsArray = Object.values(builtinToolConfigs).map((config) => ({
    tool_name: config.tool_name as string,
    requires_user_confirmation: !!config.requires_user_confirmation,
    enabled: config.enabled !== undefined ? config.enabled : true,
    disabled_methods: config.disabled_methods,
  }));

  // Reconstruct events array using new format
  const eventConfigs: Record<
    number,
    {
      event_type: string;
      config?: Record<string, unknown> | null;
      enabled: boolean;
    }
  > = {};
  formData.forEach((value, key) => {
    const match = key.match(/events_config\.events\[(\d+)\]\.([^\]]+)/);
    if (match) {
      const index = parseInt(match[1], 10);
      const field = match[2] as "event_type" | "config" | "enabled";
      if (!eventConfigs[index]) {
        eventConfigs[index] = { event_type: "", enabled: true };
      }
      // Handle potential JSON parsing for config
      if (field === "config") {
        if (typeof value === "string" && value.trim()) {
          try {
            eventConfigs[index].config = JSON.parse(value);
          } catch (parseError) {
            console.error(
              `Failed to parse event config JSON for index ${index}:`,
              parseError
            );
            eventConfigs[index].config = {
              error: "INVALID_JSON",
            } as unknown as Record<string, unknown>;
          }
        } else {
          eventConfigs[index].config = null;
        }
      } else if (field === "event_type") {
        eventConfigs[index].event_type = value as string;
      } else if (field === "enabled") {
        eventConfigs[index].enabled = value === "on" || value === "true";
      }
    }
  });
  const eventConfigsArray = Object.values(eventConfigs);

  // Get form values
  const name = formData.get("name") as string;
  const description = formData.get("description") as string;
  const instruction = formData.get("instruction") as string;
  const model_id = formData.get("model_id") as string;

  const rawFormData = {
    name,
    description,
    instruction,
    model_id,
    tools_config: {
      mcp_server_configs: mcpConfigsArray,
      builtin_tools: builtinToolsArray,
    },
    events_config: { events: eventConfigsArray },
    planning: formData.get("planning") === "on",
  };

  const validatedFields = AgentSchema.safeParse(rawFormData);

  if (!validatedFields.success) {
    // Attempt to map Zod errors to the nested structure
    const mappedErrors: { [key: string]: string[] } = {}; // Use the simplified error structure
    for (const issue of validatedFields.error.issues) {
      const path = issue.path.join(".");
      if (!mappedErrors[path]) {
        mappedErrors[path] = [];
      }
      mappedErrors[path].push(issue.message);
    }
    return {
      message: "Validation failed. Please check the fields.",
      errors: mappedErrors,
      fieldValues: rawFormData,
    };
  }

  try {
    // Call backend API to create agent - send both description and instruction
    const { data, error } = await createAgent({
      name: validatedFields.data.name,
      description: validatedFields.data.description || "",
      instruction: validatedFields.data.instruction,
      model_id: validatedFields.data.model_id,
      tools_config: validatedFields.data.tools_config || null,
      events_config: validatedFields.data.events_config
        ? {
            events: validatedFields.data.events_config.events || null,
          }
        : null,
      planning: validatedFields.data.planning || null,
    });

    if (error) {
      // If the error is from the API, extract field errors if possible
      const errorMessage =
        (error as any)?.message ||
        (error as any)?.detail?.[0]?.msg ||
        "Unknown error";
      return {
        message: "Failed to create agent",
        errors: { _form: [`API error: ${errorMessage}`] },
        fieldValues: validatedFields.data,
      };
    }

    if (data) {
      // Return success state with created agent data
      return {
        message: "Agent created successfully!",
        fieldValues: {
          ...validatedFields.data,
          id: data.id, // Include the agent ID
        },
      };
    }
  } catch (err) {
    // Handle unexpected errors (network, etc.)
    return {
      message: "Failed to create agent",
      errors: {
        _form: [
          `Unexpected error: ${err instanceof Error ? err.message : "Unknown error"}`,
        ],
      },
      fieldValues: validatedFields.data,
    };
  }

  return {
    message: "Unknown error occurred",
    errors: { _form: ["Unknown error occurred"] },
    fieldValues: validatedFields.data,
  };
}
