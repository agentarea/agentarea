import { notFound } from "next/navigation";
import { getAgent, getModelInstance } from "@/lib/api";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTranslations } from "next-intl/server";
import AgentPageClient from "./components/AgentPageClient";

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AgentDetailPage({ params }: Props) {
  const { id } = await params;
  const agentResponse = await getAgent(id);
  const t = await getTranslations("Agent");
  if (!agentResponse.data) {
    notFound();
  }

  const agent = agentResponse.data;

  // Fetch model instance data if agent has a model_id
  let modelInfo = null;
  if (agent.model_id) {
    const modelResponse = await getModelInstance(agent.model_id);
    if (modelResponse.data) {
      modelInfo = {
        provider_name: modelResponse.data.provider_name || undefined,
        model_display_name: modelResponse.data.model_display_name || undefined,
        config_name: modelResponse.data.config_name || undefined
      };
    }
  }

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          {label: t("browseAgents"), href: "/agents"},
          {label: agent.name, href: `/agents/${agent.id}`},
        ],
        // description: agent.description || "Agent details and interaction",
        // controls: (
        //   <DeleteAgentButton
        //     agentId={agent.id}
        //     agentName={agent.name}
        //   />
        // ),
      }}
    >
      <AgentPageClient agent={agent} modelInfo={modelInfo} />
    </ContentBlock>
  );
}
