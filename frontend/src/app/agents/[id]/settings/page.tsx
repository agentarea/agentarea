import { getTranslations } from "next-intl/server";
import AgentPageWrapper from "../../shared/AgentPageWrapper";
import AgentEditContent from "./AgentEditContent";

interface AgentSettingsPageProps {
  params: {
    id: string;
  };
}

export default async function AgentSettingsPage({ params }: AgentSettingsPageProps) {
  const t = await getTranslations("Agent");

  return (
    <AgentPageWrapper
      breadcrumb={[
        {label: t("browseAgents"), href: "/agents"},
      ]}
      useContentBlock={false}
      className="h-full w-full px-4 py-5"
    >
      <AgentEditContent agentId={params.id} />
    </AgentPageWrapper>
  );
}