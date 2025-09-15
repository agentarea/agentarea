import { Agent } from "@/types";

interface ToolAvatar {
  imageUrl: string;
  name: string;
  type: 'builtin' | 'mcp';
}

// Tool icons mapping - you can add more as needed
const BUILTIN_TOOL_ICONS: Record<string, string> = {
  calculator: "https://cdn-icons-png.flaticon.com/64/3406/3406679.png", // Calculator icon
  weather: "https://cdn-icons-png.flaticon.com/64/1163/1163661.png",     // Weather icon
  web_search: "https://cdn-icons-png.flaticon.com/64/3917/3917132.png"   // Search icon
};

// MCP Server icons - these could come from server metadata in the future
const MCP_SERVER_ICONS: Record<string, string> = {
  github: "https://github.githubassets.com/assets/GitHub-Mark-ea2971cee799.png",
  jira: "https://cdn.worldvectorlogo.com/logos/jira-1.svg", 
  notion: "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/Notion-logo.svg/2048px-Notion-logo.svg.png",
  slack: "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQ2sSeQqjaUTuZ3gRgkKjidpaipF_l6s72lBw&s",
  default: "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQiiqczgVWrWg2wpS5wC5iW2u3ppLqauc10yw&s"
};

/**
 * Extract tools from agent's tools_config and convert to avatar format
 */
export function getToolAvatars(agent: Agent): ToolAvatar[] {
  const toolAvatars: ToolAvatar[] = [];
  
  if (!agent.tools_config) {
    return toolAvatars;
  }

  // Add builtin tools
  if (agent.tools_config.builtin_tools && Array.isArray(agent.tools_config.builtin_tools)) {
    for (const tool of agent.tools_config.builtin_tools) {
      if (typeof tool === 'object' && tool.tool_name) {
        const iconUrl = BUILTIN_TOOL_ICONS[tool.tool_name] || BUILTIN_TOOL_ICONS.calculator;
        toolAvatars.push({
          imageUrl: iconUrl,
          name: tool.tool_name,
          type: 'builtin'
        });
      }
    }
  }

  // Add MCP server tools
  if (agent.tools_config.mcp_server_configs && Array.isArray(agent.tools_config.mcp_server_configs)) {
    for (const serverConfig of agent.tools_config.mcp_server_configs) {
      if (typeof serverConfig === 'object' && serverConfig.mcp_server_id) {
        // For now, we'll use generic MCP icons
        // In the future, this could be enhanced to show specific server icons
        const iconUrl = MCP_SERVER_ICONS.default;
        toolAvatars.push({
          imageUrl: iconUrl,
          name: `MCP Server: ${serverConfig.mcp_server_id}`,
          type: 'mcp'
        });
      }
    }
  }

  return toolAvatars;
}

/**
 * Convert tool avatars to the format expected by AvatarCircles component
 */
export function getToolAvatarUrls(agent: Agent): { imageUrl: string }[] {
  const toolAvatars = getToolAvatars(agent);
  return toolAvatars.map(tool => ({ imageUrl: tool.imageUrl }));
}

/**
 * Get a summary of tools for display
 */
export function getToolsSummary(agent: Agent): string {
  const toolAvatars = getToolAvatars(agent);
  
  if (toolAvatars.length === 0) {
    return "No tools configured";
  }
  
  const builtinCount = toolAvatars.filter(t => t.type === 'builtin').length;
  const mcpCount = toolAvatars.filter(t => t.type === 'mcp').length;
  
  const parts: string[] = [];
  if (builtinCount > 0) parts.push(`${builtinCount} builtin tool${builtinCount > 1 ? 's' : ''}`);
  if (mcpCount > 0) parts.push(`${mcpCount} MCP server${mcpCount > 1 ? 's' : ''}`);
  
  return parts.join(', ');
}
