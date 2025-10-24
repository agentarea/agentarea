import { loadAgentData } from "../shared/useAgentData";
import CreateAgentClient from "./CreateAgentClient";

export default async function CreateAgentContent() {
  const agentData = await loadAgentData();

  return (
    <CreateAgentClient
      mcpServers={agentData.mcpServers}
      llmModelInstances={agentData.llmModelInstances}
      mcpInstanceList={agentData.mcpInstanceList}
      builtinTools={agentData.builtinTools}
    />
  );
}
