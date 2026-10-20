import { getTranslations } from "next-intl/server";
import { listAgentPresets } from "@/lib/api";
import { loadStreamOptions } from "@/app/w/[workspace]/(main)/triggers/create/streamOptions";
import { loadAgentData, loadDelegationData } from "../shared/useAgentData";
import CreateAgentClient from "./CreateAgentClient";
import { generateAgentName } from "./utils/agentNameGenerator";

export default async function CreateAgentContent() {
  const tCreate = await getTranslations("TriggersPage.create");
  const [agentData, delegation, presetsResponse, streams] = await Promise.all([
    loadAgentData(),
    loadDelegationData(),
    listAgentPresets(),
    loadStreamOptions(tCreate("streamsLoadFailed")),
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
      streams={streams}
      delegation={delegation}
    />
  );
}
