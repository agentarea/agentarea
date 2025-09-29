import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTranslations } from "next-intl/server";
import { Suspense } from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import CreateAgentContent from "./CreateAgentContent";

export default async function CreateAgentPage() {
  const t = await getTranslations("Agent");
  const tCommon = await getTranslations("Common");

  return (
    <ContentBlock 
      header={{
        // title: "Create Agent",
        breadcrumb: [
          {label: t("browseAgents"), href: "/agents"},
          {label: tCommon("create")},
          {label: t("newAgent")},
        ],
    }}>
      <Suspense fallback={
        <div className="flex items-center justify-center h-32">
          <LoadingSpinner />
        </div>
      }>
        {/* Server component that loads data and renders the client form */}
        <CreateAgentContent />
      </Suspense>
    </ContentBlock>
  );
}
