import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import AgentPageWrapper from "../shared/AgentPageWrapper";
import CreateAgentContent from "./CreateAgentContent";
import { LoadingSpinner } from "@/components/LoadingSpinner";

export default async function CreateAgentPage() {
  const t = await getTranslations("Agent");
  const tCommon = await getTranslations("Common");

  return (
    <AgentPageWrapper
      breadcrumb={[
        {label: t("browseAgents"), href: "/agents"},
        {label: tCommon("create")},
        {label: t("newAgent")},
      ]}
      useContentBlock={true}
    >
      <Suspense fallback={
        <div className="flex items-center justify-center h-32">
          <LoadingSpinner />
        </div>
      }>
        <CreateAgentContent />
      </Suspense>
    </AgentPageWrapper>
  );
}
