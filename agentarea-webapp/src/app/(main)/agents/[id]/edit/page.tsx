import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import {
  getAgent,
  listAllTools,
  listMCPServerInstances,
  listMCPServers,
  listModelInstances,
  listSkills,
} from "@/lib/api";
import EditAgentClient from "./EditAgentClient";

interface Props {
  params: Promise<{ id: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { id } = await params;
  const agent = await getAgent(id);
  const t = await getTranslations("Metadata");
  return {
    title: agent.data?.name
      ? t("editAgent", { agentName: agent.data.name })
      : t("editAgent", { agentName: "Agent" }),
  };
}

export default async function EditAgentPage({ params }: Props) {
  const { id } = await params;
  try {
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

    if (!agentResponse.data) {
      notFound();
    }

    const agent = agentResponse.data;
    const mcpServers = (mcpResponse.data || []).map((server: any) => ({
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
  } catch (error) {
    console.error("Error loading agent:", error);
    notFound();
  }
}
