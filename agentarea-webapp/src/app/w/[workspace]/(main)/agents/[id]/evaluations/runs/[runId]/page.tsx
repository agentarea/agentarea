import type { Metadata } from "next";
import type { EvalRunDetail, RevisionResponse } from "@/api/client/types.gen";
import { getAgent } from "@/lib/api";
import { getEvalRun, listRevisions } from "@/lib/api-evals";
import { requireApiData } from "@/lib/server-resource";
import RunDetailClient from "./RunDetailClient";

export const metadata: Metadata = { title: "Evaluation" };

interface Props {
  params: Promise<{ id: string; runId: string }>;
}

export default async function EvalRunPage({ params }: Props) {
  const { id, runId } = await params;
  const agent = requireApiData(await getAgent(id), "agent");
  const [run, revisions] = await Promise.all([
    getEvalRun(agent.id, runId),
    listRevisions(agent.id),
  ]);
  const detail = requireApiData(run, "evaluation") as EvalRunDetail;
  return (
    <RunDetailClient
      agentId={agent.id}
      agentRef={agent.slug || agent.id}
      run={detail}
      revisions={(revisions.data ?? []) as RevisionResponse[]}
    />
  );
}
