import { loadAgentEditData, loadDelegationData } from "../../shared/useAgentData";
import AgentEditClient from "./AgentEditClient";

interface AgentEditContentProps {
  agentId: string;
}

export default async function AgentEditContent({
  agentId,
}: AgentEditContentProps) {
  const [agentData, delegation] = await Promise.all([
    loadAgentEditData(agentId),
    loadDelegationData(),
  ]);

  return (
    <AgentEditClient
      agentId={agentId}
      agentName={agentData.agent.name}
      mcpServers={agentData.mcpServers}
      llmModelInstances={agentData.llmModelInstances}
      mcpInstanceList={agentData.mcpInstanceList}
      builtinTools={agentData.builtinTools}
      initialData={agentData.initialData}
      delegation={delegation}
    />
  );
}
