import { loadAgentEditData } from "../../shared/useAgentData";
import AgentEditClient from "./AgentEditClient";
import { WalletConfigPanel } from "@/components/WalletConfig";

interface AgentEditContentProps {
  agentId: string;
}

export default async function AgentEditContent({
  agentId,
}: AgentEditContentProps) {
  const agentData = await loadAgentEditData(agentId);

  return (
    <div className="space-y-8">
      <AgentEditClient
        agentId={agentId}
        mcpServers={agentData.mcpServers}
        llmModelInstances={agentData.llmModelInstances}
        mcpInstanceList={agentData.mcpInstanceList}
        builtinTools={agentData.builtinTools}
        initialData={agentData.initialData}
      />
      <WalletConfigPanel agentId={agentId} />
    </div>
  );
}
