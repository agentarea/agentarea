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
  // The page is addressed by the agent's slug; the API keys, the save and the
  // delegate list all go by its id.
  const { id } = agentData.agent;
  const agentKeys = await loadAgentKeys(id);
  const a2aAddress = agentData.agent.a2a_url;

  return (
    <AgentEditClient
      agentId={id}
      agentName={agentData.agent.name}
      mcpServers={agentData.mcpServers}
      llmModelInstances={agentData.llmModelInstances}
      mcpInstanceList={agentData.mcpInstanceList}
      builtinTools={agentData.builtinTools}
      toolVerdicts={agentData.toolVerdicts}
      initialData={agentData.initialData}
      delegation={delegation}
      a2aAccess={a2aAddress ? { address: a2aAddress, keys: agentKeys } : null}
    />
  );
}
