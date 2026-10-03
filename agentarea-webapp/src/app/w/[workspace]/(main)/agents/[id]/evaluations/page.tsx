import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import type {
  CaseResponse,
  EvalRunResponse,
  RevisionResponse,
  SuiteResponse,
} from "@/api/client/types.gen";
import RetryEmptyState from "@/components/EmptyState/RetryEmptyState";
import { getAgent } from "@/lib/api";
import {
  listCases,
  listEvalRuns,
  listRevisions,
  listSuites,
} from "@/lib/api-evals";
import { requireApiData } from "@/lib/server-resource";
import EvaluationsClient from "./EvaluationsClient";

export const metadata: Metadata = { title: "Agent Evaluations" };

interface Props {
  params: Promise<{ id: string }>;
  searchParams: Promise<{ candidate?: string; suite?: string }>;
}

export default async function AgentEvaluationsPage({
  params,
  searchParams,
}: Props) {
  const { id } = await params;
  const { candidate, suite } = await searchParams;
  const t = await getTranslations("AgentEvals");
  const agent = requireApiData(await getAgent(id), "agent");
  const [suites, runs, revisions] = await Promise.all([
    listSuites(),
    listEvalRuns(agent.id),
    listRevisions(agent.id),
  ]);
  if (suites.error || runs.error || revisions.error) {
    return (
      <RetryEmptyState
        title={t("common.loadFailed")}
        description={t("evaluations.description")}
        iconsType="agent"
      />
    );
  }
  const suiteList = (suites.data ?? []) as SuiteResponse[];
  const casesBySuite: Record<string, CaseResponse[]> = {};
  await Promise.all(
    suiteList.map(async (s) => {
      const cases = await listCases(s.id);
      casesBySuite[s.id] = (cases.data ?? []) as CaseResponse[];
    })
  );
  return (
    <EvaluationsClient
      agentId={agent.id}
      agentRef={agent.slug || agent.id}
      suites={suiteList}
      casesBySuite={casesBySuite}
      runs={(runs.data ?? []) as EvalRunResponse[]}
      revisions={(revisions.data ?? []) as RevisionResponse[]}
      initialCandidate={candidate ?? null}
      initialSuite={suite ?? null}
    />
  );
}
