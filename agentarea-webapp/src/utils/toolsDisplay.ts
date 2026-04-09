import { Agent } from "@/types";

interface ToolAvatar {
  imageUrl: string;
  name: string;
  type: "builtin" | "mcp" | "openapi";
}

// Tool icons mapping - you can add more as needed
const BUILTIN_TOOL_ICONS: Record<string, string> = {
  calculator: "https://cdn-icons-png.flaticon.com/64/3406/3406679.png", // Calculator icon
  weather: "https://cdn-icons-png.flaticon.com/64/1163/1163661.png", // Weather icon
  web_search: "https://cdn-icons-png.flaticon.com/64/3917/3917132.png", // Search icon
};

// OpenAPI Connection icons - fallback to generic API icon
const OPENAPI_CONNECTION_ICONS: Record<string, string> = {
  default:
    "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQiiqczgVWrWg2wpS5wC5iW2u3ppLqauc10yw&s",
};

// MCP Server icons - these could come from server metadata in the future
const MCP_SERVER_ICONS: Record<string, string> = {
  github: "https://github.githubassets.com/assets/GitHub-Mark-ea2971cee799.png",
  jira: "https://cdn.worldvectorlogo.com/logos/jira-1.svg",
  notion:
    "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/Notion-logo.svg/2048px-Notion-logo.svg.png",
  slack:
    "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQ2sSeQqjaUTuZ3gRgkKjidpaipF_l6s72lBw&s",
  default:
    "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQiiqczgVWrWg2wpS5wC5iW2u3ppLqauc10yw&s",
};

/**
 * Extract tools from agent's tools array and convert to avatar format
 */
export function getToolAvatars(agent: Agent): ToolAvatar[] {
  const toolAvatars: ToolAvatar[] = [];

  if (!agent.tools || !Array.isArray(agent.tools)) {
    return toolAvatars;
  }

  for (const tool of agent.tools) {
    if (tool.type === "code") {
      const iconUrl =
        BUILTIN_TOOL_ICONS[tool.name] || BUILTIN_TOOL_ICONS.calculator;
      toolAvatars.push({
        imageUrl: iconUrl,
        name: tool.name,
        type: "builtin",
      });
    } else if (tool.type === "mcp") {
      const serverName = tool.name.toLowerCase();
      const iconUrl = MCP_SERVER_ICONS[serverName] || MCP_SERVER_ICONS.default;
      toolAvatars.push({
        imageUrl: iconUrl,
        name: tool.name,
        type: "mcp",
      });
    } else if (tool.type === "openapi") {
      const connectionName = tool.name.toLowerCase();
      const iconUrl =
        OPENAPI_CONNECTION_ICONS[connectionName] ||
        OPENAPI_CONNECTION_ICONS.default;
      toolAvatars.push({
        imageUrl: iconUrl,
        name: tool.name,
        type: "openapi",
      });
    }
  }

  return toolAvatars;
}

/**
 * Convert tool avatars to the format expected by AvatarCircles component
 */
export function getToolAvatarUrls(agent: Agent): { imageUrl: string }[] {
  const toolAvatars = getToolAvatars(agent);
  return toolAvatars.map((tool) => ({ imageUrl: tool.imageUrl }));
}

/**
 * Get a summary of tools for display
 */
export function getToolsSummary(agent: Agent): string {
  const toolAvatars = getToolAvatars(agent);

  if (toolAvatars.length === 0) {
    return "No tools configured";
  }

  const builtinCount = toolAvatars.filter((t) => t.type === "builtin").length;
  const mcpCount = toolAvatars.filter((t) => t.type === "mcp").length;
  const openapiCount = toolAvatars.filter((t) => t.type === "openapi").length;

  const parts: string[] = [];
  if (builtinCount > 0)
    parts.push(`${builtinCount} builtin tool${builtinCount > 1 ? "s" : ""}`);
  if (mcpCount > 0)
    parts.push(`${mcpCount} MCP server${mcpCount > 1 ? "s" : ""}`);
  if (openapiCount > 0)
    parts.push(`${openapiCount} OpenAPI${openapiCount > 1 ? " connections" : " connection"}`);

  return parts.join(", ");
}

/**
 * Get detailed list of tools for display
 */
export function getToolsList(agent: Agent): string {
  const toolAvatars = getToolAvatars(agent);

  if (toolAvatars.length === 0) {
    return "No tools configured";
  }

  const toolNames = toolAvatars.map((tool) => {
    if (tool.type === "builtin") {
      return tool.name;
    } else {
      return tool.name; // Already includes "MCP Server: " prefix
    }
  });

  return toolNames.join(", ");
}

/**
 * Get tools data for component display with icons
 */
export function getToolsForDisplay(agent: Agent): ToolAvatar[] {
  return getToolAvatars(agent);
}

/**
 * Extract tools from agent's tools array (new format) or tools_config (legacy format)
 * Used in network topology display
 */
export function getToolsFromConfig(toolsConfig: any): ToolAvatar[] {
  const toolAvatars: ToolAvatar[] = [];

  if (!toolsConfig) {
    return toolAvatars;
  }

  // New format: array of { type, name, settings }
  if (Array.isArray(toolsConfig)) {
    for (const tool of toolsConfig) {
      if (typeof tool === "object" && tool.name) {
        if (tool.type === "code" || tool.type === "builtin") {
          const iconUrl =
            BUILTIN_TOOL_ICONS[tool.name] || BUILTIN_TOOL_ICONS.calculator;
          toolAvatars.push({
            imageUrl: iconUrl,
            name: tool.name,
            type: "builtin",
          });
        } else if (tool.type === "mcp") {
          const serverId = tool.name.toLowerCase();
          const iconUrl =
            MCP_SERVER_ICONS[serverId] || MCP_SERVER_ICONS.default;
          toolAvatars.push({
            imageUrl: iconUrl,
            name: tool.name,
            type: "mcp",
          });
        } else if (tool.type === "openapi") {
          const connectionName = tool.name.toLowerCase();
          const iconUrl =
            OPENAPI_CONNECTION_ICONS[connectionName] ||
            OPENAPI_CONNECTION_ICONS.default;
          toolAvatars.push({
            imageUrl: iconUrl,
            name: tool.name,
            type: "openapi",
          });
        }
      }
    }
    return toolAvatars;
  }

  // Legacy format: { builtin_tools: [], mcp_server_configs: [] }
  if (typeof toolsConfig === "object") {
    if (toolsConfig.builtin_tools && Array.isArray(toolsConfig.builtin_tools)) {
      for (const tool of toolsConfig.builtin_tools) {
        if (typeof tool === "object" && tool.tool_name) {
          const iconUrl =
            BUILTIN_TOOL_ICONS[tool.tool_name] || BUILTIN_TOOL_ICONS.calculator;
          toolAvatars.push({
            imageUrl: iconUrl,
            name: tool.tool_name,
            type: "builtin",
          });
        }
      }
    }

    if (
      toolsConfig.mcp_server_configs &&
      Array.isArray(toolsConfig.mcp_server_configs)
    ) {
      for (const serverConfig of toolsConfig.mcp_server_configs) {
        if (typeof serverConfig === "object" && serverConfig.mcp_server_id) {
          const serverId = serverConfig.mcp_server_id.toLowerCase();
          const iconUrl =
            MCP_SERVER_ICONS[serverId] || MCP_SERVER_ICONS.default;
          toolAvatars.push({
            imageUrl: iconUrl,
            name: serverConfig.mcp_server_id,
            type: "mcp",
          });
        }
      }
    }

    if (
      toolsConfig.openapi_configs &&
      Array.isArray(toolsConfig.openapi_configs)
    ) {
      for (const openapiConfig of toolsConfig.openapi_configs) {
        if (typeof openapiConfig === "object" && openapiConfig.openapi_connection_id) {
          const connectionName = (
            openapiConfig.openapi_connection_name ||
            openapiConfig.openapi_connection_id
          ).toLowerCase();
          const iconUrl =
            OPENAPI_CONNECTION_ICONS[connectionName] ||
            OPENAPI_CONNECTION_ICONS.default;
          toolAvatars.push({
            imageUrl: iconUrl,
            name: openapiConfig.openapi_connection_name || openapiConfig.openapi_connection_id,
            type: "openapi",
          });
        }
      }
    }
  }

  return toolAvatars;
}

/**
 * Convert tools config to avatar URLs (for network topology)
 */
export function getToolAvatarUrlsFromConfig(
  toolsConfig: any
): { imageUrl: string }[] {
  const toolAvatars = getToolsFromConfig(toolsConfig);
  return toolAvatars.map((tool) => ({ imageUrl: tool.imageUrl }));
}
