import type { Metadata } from "next";
import {
  getAgentAction,
  listAgentsAction,
} from "@/lib/server-actions";
import { DelegationConfig } from "./DelegationConfig";

export const metadata: Metadata = {
  title: "Agent Delegation",
};

interface AgentDelegationPageProps {
  params: Promise<{
    id: string;
  }>;
}

export default async function AgentDelegationPage({
  params,
}: AgentDelegationPageProps) {
  const resolvedParams = await params;
  const [agentResult, agentsResult] = await Promise.all([
    getAgentAction(resolvedParams.id),
    listAgentsAction(),
  ]);

  const agent = agentResult.data;
  const allAgents = agentsResult.data ?? [];

  const otherAgents = allAgents.filter(
    (a: { id: string }) => a.id !== resolvedParams.id
  );

  const connectedAgentNames = new Set<string>(
    (agent?.tools ?? [])
      .filter((t: { type: string }) => t.type === "agent")
      .map((t: { name: string }) => t.name)
  );

  return (
    <div className="h-full space-y-2 overflow-auto px-4 py-5">
      <DelegationConfig
        agentId={resolvedParams.id}
        otherAgents={otherAgents}
        connectedAgentNames={connectedAgentNames}
        currentTools={agent?.tools ?? []}
      />
    </div>
  );
}
