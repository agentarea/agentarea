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
  // Keep all in-page navigation on the slug when available, so opening by slug
  // doesn't bounce back to the id once a tab/breadcrumb is clicked.
  const agentRef = agent.slug || agent.id;

  return (
    <ChatProvider>
      <ContentBlock
        header={{
          breadcrumb: [
            { label: t("browseAgents"), href: "/agents" },
            { label: agent.name, href: `/agents/${agentRef}` },
          ],
          controls: <AgentHeaderControls />,
        }}
        className="p-0 h-full"
        subheader={<AgentHeaderTabs agentId={agentRef} />}
      >
        {children}
      </ContentBlock>
    </ChatProvider>
  );
}
