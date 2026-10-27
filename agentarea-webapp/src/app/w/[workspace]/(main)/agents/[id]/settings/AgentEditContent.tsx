import {
  loadAgentEditData,
  loadAgentKeys,
  loadDelegationData,
} from "../../shared/useAgentData";
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
  // The route may carry the slug; keys are bound to the agent's id.
  const agentKeys = await loadAgentKeys(agentData.agent.id);
  const a2aAddress = agentData.agent.a2a_url;

  return (
    <AgentEditClient
      agentId={agentData.agent.id}
      agentName={agentData.agent.name}
      mcpServers={agentData.mcpServers}
      llmModelInstances={agentData.llmModelInstances}
      mcpInstanceList={agentData.mcpInstanceList}
      builtinTools={agentData.builtinTools}
      initialData={agentData.initialData}
      delegation={delegation}
      a2aAccess={a2aAddress ? { address: a2aAddress, keys: agentKeys } : null}
    />
  );
}
