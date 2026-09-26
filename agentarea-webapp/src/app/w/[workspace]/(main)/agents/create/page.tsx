import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { FormSkeleton } from "@/components/Skeleton";
import AgentPageWrapper from "../shared/AgentPageWrapper";
import { ChatProvider } from "../shared/ChatContext";
import CreateAgentContent from "./CreateAgentContent";
import CreateAgentHeaderControls from "./CreateAgentHeaderControls";

export const metadata: Metadata = {
  title: "Create Agent",
};

export default async function CreateAgentPage() {
  const t = await getTranslations("AgentsPage");

  return (
    <ChatProvider>
      <AgentPageWrapper
        breadcrumb={[
          { label: t("browseAgents"), href: "/agents" },
          { label: t("newAgent") },
        ]}
        useContentBlock={true}
        controls={<CreateAgentHeaderControls label={t("createAgent")} />}
      >
        <Suspense fallback={<FormSkeleton className="p-4" />}>
          <CreateAgentContent />
        </Suspense>
      </AgentPageWrapper>
    </ChatProvider>
  );
}
