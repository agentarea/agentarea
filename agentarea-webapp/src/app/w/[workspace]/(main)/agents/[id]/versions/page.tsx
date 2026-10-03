import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import type {
  RevisionOutcomeResponse,
  RevisionResponse,
} from "@/api/client/types.gen";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { getAgent } from "@/lib/api";
import { listRevisionOutcomes, listRevisions } from "@/lib/api-evals";
import { requireApiData } from "@/lib/server-resource";
import VersionsClient from "./VersionsClient";

export const metadata: Metadata = { title: "Agent Versions" };

interface Props {
  params: Promise<{ id: string }>;
}

export default async function AgentVersionsPage({ params }: Props) {
  const { id } = await params;
  const t = await getTranslations("AgentEvals");
  const agent = requireApiData(await getAgent(id), "agent");
  const [revisions, outcomes] = await Promise.all([
    listRevisions(agent.id),
    listRevisionOutcomes(agent.id),
  ]);
  if (revisions.error || outcomes.error) {
    return (
      <RetryEmptyState
        title={t("common.loadFailed")}
        description={t("versions.description")}
        iconsType="agent"
      />
    );
  }
  return (
    <VersionsClient
      agentId={agent.id}
      agentRef={agent.slug || agent.id}
      instruction={agent.instruction ?? ""}
      revisions={(revisions.data ?? []) as RevisionResponse[]}
      outcomes={(outcomes.data ?? []) as RevisionOutcomeResponse[]}
    />
  );
}
