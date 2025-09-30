import { notFound } from "next/navigation";
import { getAgent } from "@/lib/api";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTranslations } from "next-intl/server";
import AgentHeaderTabs from "./components/AgentHeaderTabs";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

export default async function AgentLayout({ params, children }: Props) {
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
          { label: t("browseAgents"), href: "/agents" },
          { label: agent.name, href: `/agents/${agent.id}` },
        ],
      }}
      className="p-0"
    >
      <div className="flex flex-col h-full">
        <div className="bg-white dark:bg-zinc-800 px-4 border-b border-zinc-200 dark:border-zinc-700">
          <AgentHeaderTabs agentId={agent.id} />
        </div>
        {children}
      </div>
    </ContentBlock>
  );
}


