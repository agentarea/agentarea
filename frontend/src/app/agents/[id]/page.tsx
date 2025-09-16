import { notFound } from "next/navigation";
import { getAgent } from "@/lib/api";
import AgentDetailClient from "./AgentDetailClient";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import DeleteAgentButton from './components/DeleteAgentButton';

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AgentDetailPage({ params }: Props) {
  const { id } = await params;
  const agentResponse = await getAgent(id);

  if (!agentResponse.data) {
    notFound();
  }

  const agent = agentResponse.data;

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          {label: "Browse Agents", href: "/agents/browse"},
          {label: agent.name, href: `/agents/${agent.id}`},
        ],
        // description: agent.description || "Agent details and interaction",
        backLink: {
          label: "Back to Browse Agents",
          href: "/agents/browse",
        },
        controls: (
          <DeleteAgentButton 
            agentId={agent.id} 
            agentName={agent.name}
          />
        ),
      }}
    >
      <AgentDetailClient agent={agent} />
    </ContentBlock>
  );
}
