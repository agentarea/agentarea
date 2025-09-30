import Link from "next/link";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getTranslations } from "next-intl/server";
import { Button } from "@/components/ui/button";
import { Suspense } from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Plus } from "lucide-react";
import AgentsContent from "@/app/agents/components/AgentsContent";

export default async function AgentsBrowsePage() {
  const t = await getTranslations("Agent");

  return (
    <ContentBlock 
      className="pt-0 px-0"
      header={{
        breadcrumb: [
          {label: t("browseAgents")},
        ],
        description: t("mainDescriptionPage"),
        controls: (
          <Link href="/agents/create">
            <Button className="shrink-0 gap-2" size="xs" data-test="deploy-button">
              <Plus className="h-5 w-5" />
              {t("deployNewAgent")}
            </Button>
          </Link>
        )
    }}>
      <Suspense
        fallback={(
          <div className="flex items-center justify-center h-32">
            <LoadingSpinner />
          </div>
        )}
      >
        <AgentsContent />
      </Suspense>
    </ContentBlock>
  );
}