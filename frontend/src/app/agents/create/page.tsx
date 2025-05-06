import { listMCPServers, MCPServer } from "@/lib/api";
import CreateAgentClient from "./CreateAgentClient";
import Link from "next/link";
import { ArrowLeft } from "lucide-react";

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

  // return <CreateAgentClient mcpServers={[mcpServers]} />;

  return (
    <div className="content">
      <div className="content-header">
        <div className="flex flex-col gap-2">
          <h1>Create Agent</h1>
          <Link href="/agents/browse" className="flex items-center gap-2 text-xs text-zinc-400 hover:text-accent transition-colors duration-300">
            <ArrowLeft className="h-4 w-4" />
            Back to Browse Agents
          </Link>
        </div>
      </div>
      <CreateAgentClient mcpServers={mcpServers} />
    </div>
  );
}
