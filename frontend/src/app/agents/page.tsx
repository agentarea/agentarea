import Link from "next/link";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { listAgents, listModelInstances } from "@/lib/api";
import AgentsList from "./components/AgentsList";
import { getTranslations } from "next-intl/server";
import { Button } from "@/components/ui/button";
import { Suspense } from "react";
import { LoadingSpinner } from "@/components/LoadingSpinner";

export default async function AgentsBrowsePage() {
  const t = await getTranslations("Agent");
  const [{ data: agents = [] }, { data: modelInstances = [] }] = await Promise.all([
    listAgents(),
    listModelInstances(),
  ]);

  const enrichedAgents = (agents as any[]).map((agent) => {
    const model = (modelInstances as any[]).find((m) => m.id === agent.model_id);
    const model_info = model
      ? {
          provider_name: model.provider_name || undefined,
          model_display_name: model.model_display_name || undefined,
          config_name: model.config_name || undefined,
        }
      : undefined;
    return { ...agent, model_info };
  });

  return (
    <ContentBlock 
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
        <AgentsList initialAgents={enrichedAgents as any} />
      </Suspense>
    </ContentBlock>
  );
}