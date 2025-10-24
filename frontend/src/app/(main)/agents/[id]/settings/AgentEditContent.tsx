import { loadAgentEditData } from "../../shared/useAgentData";
import AgentEditClient from "./AgentEditClient";

interface AgentEditContentProps {
  agentId: string;
}

export default async function AgentEditContent({
  agentId,
}: AgentEditContentProps) {
  const agentData = await loadAgentEditData(agentId);

  return (
    <AgentEditClient
      agentId={agentId}
      agent={agentData.agent}
      mcpServers={agentData.mcpServers}
      llmModelInstances={agentData.llmModelInstances}
      mcpInstanceList={agentData.mcpInstanceList}
      builtinTools={agentData.builtinTools}
      initialData={agentData.initialData}
    />
  );
}
