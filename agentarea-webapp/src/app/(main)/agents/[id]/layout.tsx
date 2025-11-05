import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getAgent } from "@/lib/api";
import AgentHeaderTabs from "./components/AgentHeaderTabs";
import AgentHeaderControls from "./components/AgentHeaderControls";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

export default async function AgentLayout({ params, children }: Props) {
  const { id } = await params;
  const agentResponse = await getAgent(id);
  const t = await getTranslations("AgentsPage");
  if (!agentResponse.data) {
    notFound();
  }

  const agent = agentResponse.data;

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("browseAgents"), href: "/agents" },
          { label: agent.name, href: `/agents/${agent.id}` },
        ],
        controls: <AgentHeaderControls />,
      }}
      className="p-0"
      subheader={<AgentHeaderTabs agentId={agent.id} />}
    >
      {children}
    </ContentBlock>
  );
}
