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
  const [agentData, delegation, agentKeys] = await Promise.all([
    loadAgentEditData(agentId),
    loadDelegationData(),
    loadAgentKeys(agentId),
  ]);
  const a2aAddress = agentData.agent.a2a_url;

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
      a2aAccess={a2aAddress ? { address: a2aAddress, keys: agentKeys } : null}
    />
  );
}
