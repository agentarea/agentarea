import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import AgentPageWrapper from "../../shared/AgentPageWrapper";
import AgentEditContent from "./AgentEditContent";
import { LoadingSpinner } from "@/components/LoadingSpinner";

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
    >
      <Suspense fallback={
        <div className="flex items-center justify-center h-32">
          <LoadingSpinner />
        </div>
      }>
        <AgentEditContent agentId={params.id} />
      </Suspense>
    </AgentPageWrapper>
  );
}