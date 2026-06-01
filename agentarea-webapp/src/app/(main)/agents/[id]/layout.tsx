import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getAgent } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import { ChatProvider } from "../shared/ChatContext";
import AgentHeaderControls from "./components/AgentHeaderControls";
import AgentHeaderTabs from "./components/AgentHeaderTabs";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

export default async function AgentLayout({ params, children }: Props) {
  const { id } = await params;
  const agentResponse = await getAgent(id);
  const t = await getTranslations("AgentsPage");
  const agent = requireApiData(agentResponse, "agent");

  return (
    <ChatProvider>
      <ContentBlock
        header={{
          breadcrumb: [
            { label: t("browseAgents"), href: "/agents" },
            { label: agent.name, href: `/agents/${agent.id}` },
          ],
          controls: <AgentHeaderControls />,
        }}
        className="p-0 h-full"
        subheader={<AgentHeaderTabs agentId={agent.id} />}
      >
        {children}
      </ContentBlock>
    </ChatProvider>
  );
}
