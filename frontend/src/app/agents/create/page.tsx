import { listMCPServers, MCPServer, listLLMModelInstances } from "@/lib/api";
import CreateAgentClient from "./CreateAgentClient";
import ContentBlock from "@/components/ContentBlock/ContentBlock";

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

  // Fetch LLM model instances
  const llmResponse = await listLLMModelInstances();
  const llmModelInstances = llmResponse.data || [];

  // return <CreateAgentClient mcpServers={[mcpServers]} />;

  return (
    <ContentBlock 
      header={{
        title: "Create Agent",
        backLink: {
          label: "Back to Browse Agents",
          href: "/agents/browse"
        }
    }}>
      <CreateAgentClient mcpServers={mcpServers} llmModelInstances={llmModelInstances} />
    </ContentBlock>
  );
}
