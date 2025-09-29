import { listMCPServers, MCPServer, listModelInstances, listMCPServerInstances, listBuiltinTools } from "@/lib/api";
import CreateAgentClient from "./CreateAgentClient";

export default async function CreateAgentContent() {
  // Fetch MCP servers on the server
  const response = await listMCPServers();
  const mcpServers: MCPServer[] = (response.data || []).map(
    (server: MCPServer) => {
      const withDownloads = server as MCPServer & { downloads?: number };
      return {
        ...server,
        status: ["published", "draft", "pending", "rejected"].includes(
          server.status
        )
          ? (server.status as MCPServer["status"])
          : "draft",
        ...(typeof withDownloads.downloads === "number"
          ? { downloads: withDownloads.downloads }
          : {}),
      };
    }
  );

  // Fetch LLM model instances
  const llmResponse = await listModelInstances();
  const llmModelInstances = llmResponse.data || [];

  // Fetch MCP server instances
  const mcpInstancesResponse = await listMCPServerInstances();
  const mcpInstanceList = mcpInstancesResponse.data || [];

  // Fetch builtin tools on the server
  const builtinToolsResponse = await listBuiltinTools();
  const builtinTools = Array.isArray(builtinToolsResponse.data)
    ? builtinToolsResponse.data
    : Object.values(builtinToolsResponse.data || {});

  return (
    <CreateAgentClient 
      mcpServers={mcpServers}
      llmModelInstances={llmModelInstances}
      mcpInstanceList={mcpInstanceList}
      builtinTools={builtinTools}
    />
  );
}


