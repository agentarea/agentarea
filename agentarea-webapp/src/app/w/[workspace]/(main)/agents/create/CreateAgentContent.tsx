import { listAgentPresets } from "@/lib/api";
import { listTriggerCatalogAction } from "@/app/w/[workspace]/(main)/triggers/create/actions";
import { loadAgentData, loadDelegationData } from "../shared/useAgentData";
import CreateAgentClient from "./CreateAgentClient";
import { generateAgentName } from "./utils/agentNameGenerator";

export default async function CreateAgentContent() {
  const [agentData, delegation, presetsResponse, triggerCatalog] = await Promise.all([
    loadAgentData(),
    loadDelegationData(),
    listAgentPresets(),
    listTriggerCatalogAction().catch((error) => {
      console.error("Failed to load trigger catalog:", error);
      return null;
    }),
  ]);
  if (presetsResponse.error) {
    console.error("Failed to load agent presets:", presetsResponse.error);
  }

  return (
    <CreateAgentClient
      suggestedName={generateAgentName()}
      mcpServers={agentData.mcpServers}
      llmModelInstances={agentData.llmModelInstances}
      mcpInstanceList={agentData.mcpInstanceList}
      builtinTools={agentData.builtinTools}
      presets={presetsResponse.error ? null : (presetsResponse.data ?? [])}
      triggerCatalog={triggerCatalog}
      delegation={delegation}
    />
  );
}
