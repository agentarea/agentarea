import type { Metadata } from "next";
import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { getAgent } from "@/lib/api";
import AgentEditContent from "./AgentEditContent";

interface AgentSettingsPageProps {
  params: Promise<{
    id: string;
  }>;
}

export async function generateMetadata({ params }: AgentSettingsPageProps): Promise<Metadata> {
  const { id } = await params;
  const agent = await getAgent(id);
  const t = await getTranslations("Metadata");
  return {
    title: agent.data?.name
      ? t("agentSettings", { agentName: agent.data.name })
      : t("agentSettings", { agentName: "Agent" }),
  };
}

export default async function AgentSettingsPage({
  params,
}: AgentSettingsPageProps) {
  const resolvedParams = await params;

  return (
    <Suspense
      fallback={
        <div className="flex h-32 items-center justify-center">
          <LoadingSpinner />
        </div>
      }
    >
      <AgentEditContent agentId={resolvedParams.id} />
    </Suspense>
  );
}
