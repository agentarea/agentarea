import { notFound } from "next/navigation";
import { getAgent } from "@/lib/api";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTranslations } from "next-intl/server";
import AgentPageClient from "./components/AgentPageClient";
import AgentHeaderTabs from "./components/AgentHeaderTabs";
import AgentContentSwitcher from "./components/AgentContentSwitcher";

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

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          {label: t("browseAgents"), href: "/agents"},
          {label: agent.name, href: `/agents/${agent.id}`},
        ],
        controls: (
          <AgentHeaderTabs />
        ),
      }}
    >
      <AgentContentSwitcher agent={agent} />
    </ContentBlock>
  );
}
