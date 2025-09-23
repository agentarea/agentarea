import { listMCPServers, MCPServer, listModelInstances, listMCPServerInstances } from "@/lib/api";
import CreateAgentClient from "./CreateAgentClient";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTranslations } from "next-intl/server";

export default async function CreateAgentPage() {
  const t = await getTranslations("Agent");
  const tCommon = await getTranslations("Common");

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

  // return <CreateAgentClient mcpServers={[mcpServers]} />;

  return (
    <ContentBlock 
      header={{
        // title: "Create Agent",
        breadcrumb: [
          {label: t("browseAgents"), href: "/agents"},
          {label: tCommon("create")},
          {label: t("newAgent")},
        ],
    }}>
      <CreateAgentClient mcpServers={mcpServers} llmModelInstances={llmModelInstances} mcpInstanceList={mcpInstanceList} />
    </ContentBlock>
  );
}
