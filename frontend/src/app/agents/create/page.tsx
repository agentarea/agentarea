import { listMCPServers, MCPServer } from "@/lib/api";
import CreateAgentClient from "./CreateAgentClient";

export default async function CreateAgentPage() {
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

  return <CreateAgentClient mcpServers={mcpServers} />;
}
