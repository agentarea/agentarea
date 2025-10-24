import type { AgentFormValues } from "../create/types";

export function createAgentFormData(data: AgentFormValues): FormData {
  const formData = new FormData();

  // Basic fields
  formData.append("name", data.name);
  formData.append("description", data.description || "");
  formData.append("instruction", data.instruction);
  formData.append("model_id", data.model_id);
  formData.append("planning", data.planning.toString());

  // Add tools config
  data.tools_config.mcp_server_configs.forEach((config: any, index: number) => {
    formData.append(
      `tools_config.mcp_server_configs[${index}].mcp_server_id`,
      config.mcp_server_id
    );
    if (config.allowed_tools) {
      config.allowed_tools.forEach((tool: any, toolIndex: number) => {
        formData.append(
          `tools_config.mcp_server_configs[${index}].allowed_tools[${toolIndex}].tool_name`,
          tool.tool_name
        );
        formData.append(
          `tools_config.mcp_server_configs[${index}].allowed_tools[${toolIndex}].requires_user_confirmation`,
          (tool.requires_user_confirmation ?? false).toString()
        );
      });
    }
  });

  // Add builtin tools config
  if (data.tools_config.builtin_tools) {
    data.tools_config.builtin_tools.forEach(
      (builtinTool: any, index: number) => {
        formData.append(
          `tools_config.builtin_tools[${index}].tool_name`,
          builtinTool.tool_name
        );
        if (builtinTool.requires_user_confirmation !== undefined) {
          formData.append(
            `tools_config.builtin_tools[${index}].requires_user_confirmation`,
            builtinTool.requires_user_confirmation.toString()
          );
        }
        if (builtinTool.enabled !== undefined) {
          formData.append(
            `tools_config.builtin_tools[${index}].enabled`,
            builtinTool.enabled.toString()
          );
        }
        if (builtinTool.disabled_methods) {
          formData.append(
            `tools_config.builtin_tools[${index}].disabled_methods`,
            JSON.stringify(builtinTool.disabled_methods)
          );
        }
      }
    );
  }

  // Add events config
  data.events_config.events.forEach((event: any, index: number) => {
    formData.append(
      `events_config.events[${index}].event_type`,
      event.event_type
    );
    if (event.config) {
      formData.append(
        `events_config.events[${index}].config`,
        JSON.stringify(event.config)
      );
    }
    formData.append(
      `events_config.events[${index}].enabled`,
      (event.enabled ?? true).toString()
    );
  });

  return formData;
}
