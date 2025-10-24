import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import AgentPageWrapper from "../shared/AgentPageWrapper";
import CreateAgentContent from "./CreateAgentContent";

export default async function CreateAgentPage() {
  const t = await getTranslations("AgentsPage");
  const tCommon = await getTranslations("Common");

  return (
    <AgentPageWrapper
      breadcrumb={[
        { label: t("browseAgents"), href: "/agents" },
        { label: tCommon("create") },
        { label: t("newAgent") },
      ]}
      useContentBlock={true}
    >
      <Suspense
        fallback={
          <div className="flex h-32 items-center justify-center">
            <LoadingSpinner />
          </div>
        }
      >
        <CreateAgentContent />
      </Suspense>
    </AgentPageWrapper>
  );
}
