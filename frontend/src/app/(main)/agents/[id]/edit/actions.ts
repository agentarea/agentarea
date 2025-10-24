"use server";

import { z } from "zod";
import type { components } from "@/api/schema";
import { updateAgent as updateAgentAPI } from "@/lib/api";
import type { AddAgentFormState } from "../../create/actions";

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

// Define Zod schema for individual Event Config items
const EventConfigItemSchema = z.object({
  event_type: z.string().min(1, "Event type is required"), // e.g., 'text_input', 'cron'
  config: z.record(z.unknown()).optional().nullable(), // For future event-specific configs
  enabled: z.boolean().optional().default(true), // Whether the event is enabled
});

const AgentUpdateSchema = z.object({
  id: z.string().uuid("Invalid agent ID"),
  name: z.string().min(1, "Agent name is required"),
  description: z.string().optional(),
  instruction: z.string().min(1, "Instruction is required"),
  model_id: z.string().min(1, "Model is required"),
  tools_config: z
    .object({
      mcp_server_configs: z.array(MCPConfigSchema).optional().nullable(),
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

export async function updateAgent(
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
      /tools_config\.mcp_server_configs\[(\d+)\]\.allowed_tools\[(\d+)\]\.(.*)/
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
        mcpToolConfigs[serverIndex][toolIndex].tool_name = value as string;
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

  // Reconstruct events array using new format
  const eventConfigs: Record<
    number,
    {
      event_type: string;
      config?: { [key: string]: unknown } | null;
      enabled: boolean;
    }
  > = {};
  formData.forEach((value, key) => {
    const match = key.match(/events_config\.events\[(\d+)\]\.(.*)/);
    if (match) {
      const index = parseInt(match[1], 10);
      const field = match[2];
      if (!eventConfigs[index]) {
        eventConfigs[index] = { event_type: "", enabled: true };
      }
      // Handle potential JSON parsing for config
      if (field === "config" && typeof value === "string" && value.trim()) {
        try {
          eventConfigs[index][field] = JSON.parse(value);
        } catch (parseError) {
          eventConfigs[index][field] = { error: "INVALID_JSON" };
          console.error(
            `Failed to parse event config JSON for index ${index}:`,
            parseError
          );
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
  const id = formData.get("id") as string;
  const name = formData.get("name") as string;
  const description = formData.get("description") as string;
  const instruction = formData.get("instruction") as string;
  const model_id = formData.get("model_id") as string;

  const rawFormData = {
    id,
    name,
    description,
    instruction,
    model_id,
    tools_config: { mcp_server_configs: mcpConfigsArray },
    events_config: { events: eventConfigsArray },
    planning: formData.get("planning") === "true",
  };

  const validatedFields = AgentUpdateSchema.safeParse(rawFormData);

  if (!validatedFields.success) {
    console.error("Validation Errors:", validatedFields.error.flatten());
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
    // Call backend API to update agent
    const { data, error } = await updateAgentAPI(validatedFields.data.id, {
      name: validatedFields.data.name,
      description: validatedFields.data.description || "",
      instruction: validatedFields.data.instruction,
      model_id: validatedFields.data.model_id,
      tools_config: validatedFields.data.tools_config,
      events_config: validatedFields.data.events_config,
      planning: validatedFields.data.planning,
    });

    if (error) {
      console.error("API error:", error);
      // If the error is from the API, extract field errors if possible
      const errorMessage = error.detail?.[0]?.msg || "Unknown error";
      return {
        message: "Failed to update agent",
        errors: { _form: [`API error: ${errorMessage}`] },
        fieldValues: validatedFields.data,
      };
    }

    if (data) {
      // Return success state with updated agent data
      return {
        message: "Agent updated successfully!",
        fieldValues: validatedFields.data,
      };
    }
  } catch (err) {
    // Handle unexpected errors (network, etc.)
    console.error("Unexpected error:", err);
    return {
      message: "Failed to update agent",
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
