import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import AgentPageWrapper from "../../shared/AgentPageWrapper";
import AgentEditContent from "./AgentEditContent";

interface AgentSettingsPageProps {
  params: Promise<{
    id: string;
  }>;
}

export default async function AgentSettingsPage({
  params,
}: AgentSettingsPageProps) {
  const t = await getTranslations("AgentsPage");
  const resolvedParams = await params;

  return (
    <AgentPageWrapper
      breadcrumb={[{ label: t("browseAgents"), href: "/agents" }]}
      useContentBlock={false}
    >
      <Suspense
        fallback={
          <div className="flex h-32 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <AgentEditContent agentId={resolvedParams.id} />
      </Suspense>
    </AgentPageWrapper>
  );
}
