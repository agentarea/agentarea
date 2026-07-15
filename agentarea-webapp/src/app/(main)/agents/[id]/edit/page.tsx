import type { Metadata } from "next";
import type { McpServerResponse } from "@/api/client/types.gen";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import {
  getAgent,
  listAllTools,
  listMCPServerInstances,
  listMCPServers,
  listModelInstances,
  listSkills,
} from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import EditAgentClient from "./EditAgentClient";

export const metadata: Metadata = {
  title: "Edit Agent",
};

interface Props {
  params: Promise<{ id: string }>;
}

export default async function EditAgentPage({ params }: Props) {
  const { id } = await params;
  const [
    agentResponse,
    mcpResponse,
    llmResponse,
    mcpInstancesResponse,
    codeToolsResponse,
    skillsResponse,
  ] = await Promise.all([
    getAgent(id),
    listMCPServers(),
    listModelInstances(),
    listMCPServerInstances(),
    listAllTools({ include: "code" }),
    listSkills(),
  ]);

  const agent = requireApiData(agentResponse, "agent");
  const rawMcpServers: McpServerResponse[] =
    (mcpResponse.data as { items?: McpServerResponse[] } | null)?.items ?? [];
  const mcpServers = rawMcpServers.map((server) => ({
    ...server,
    status: ["published", "draft", "pending", "rejected"].includes(
      server.status
    )
      ? server.status
      : "draft",
  }));
  const llmModelInstances = llmResponse.data || [];
  const mcpInstanceList = mcpInstancesResponse.data || [];
  const builtinTools = codeToolsResponse.data || [];
  const availableSkills = skillsResponse.data || [];

  return (
    <ContentBlock
      header={{
        title: "Edit Agent",
        backLink: {
          label: "Back to Browse Agents",
          href: "/agents",
        },
      }}
    >
      <EditAgentClient
        agent={agent}
        mcpServers={mcpServers}
        llmModelInstances={llmModelInstances}
        mcpInstanceList={mcpInstanceList}
        builtinTools={builtinTools}
        availableSkills={availableSkills}
      />
    </ContentBlock>
  );
}
