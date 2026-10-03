import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import type {
  EvalRunResponse,
  ExperimentResponse,
  RevisionResponse,
} from "@/api/client/types.gen";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { getAgent } from "@/lib/api";
import { listEvalRuns, listExperiments, listRevisions } from "@/lib/api-evals";
import { requireApiData } from "@/lib/server-resource";
import ExperimentsClient from "./ExperimentsClient";

export const metadata: Metadata = { title: "Agent Experiments" };

interface Props {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ candidate?: string }>;
}

export default async function AgentExperimentsPage({
  params,
  searchParams,
}: Props) {
  const { id } = await params;
  const { candidate } = await searchParams;
  const t = await getTranslations("AgentEvals");
  const agent = requireApiData(await getAgent(id), "agent");
  const [experiments, revisions, evalRuns] = await Promise.all([
    listExperiments(agent.id),
    listRevisions(agent.id),
    listEvalRuns(agent.id),
  ]);
  if (experiments.error || revisions.error || evalRuns.error) {
    return (
      <RetryEmptyState
        title={t("common.loadFailed")}
        description={t("experiments.description")}
        iconsType="agent"
      />
    );
  }
  return (
    <ExperimentsClient
      agentId={agent.id}
      agentRef={agent.slug || agent.id}
      experiments={(experiments.data ?? []) as ExperimentResponse[]}
      revisions={(revisions.data ?? []) as RevisionResponse[]}
      evalRuns={(evalRuns.data ?? []) as EvalRunResponse[]}
      initialCandidate={candidate ?? null}
    />
  );
}
