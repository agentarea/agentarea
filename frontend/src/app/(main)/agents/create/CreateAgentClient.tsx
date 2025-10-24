"use client";

import React from "react";
import { useRouter } from "next/navigation";
import type { components } from "@/api/schema";
import AgentForm from "../shared/AgentForm";
import { createAgentFormData } from "../shared/formDataUtils";
import { addAgent } from "./actions";
import { generateAgentName } from "./utils/agentNameGenerator";

type MCPServer = components["schemas"]["MCPServerResponse"];
type LLMModelInstance = components["schemas"]["ModelInstanceResponse"];

export default function CreateAgentClient({
  mcpServers,
  llmModelInstances,
  mcpInstanceList,
  builtinTools,
}: {
  mcpServers: MCPServer[];
  llmModelInstances: LLMModelInstance[];
  mcpInstanceList: any[];
  builtinTools: any[];
}) {
  const router = useRouter();

  const handleSubmit = async (data: any) => {
    const formData = createAgentFormData(data);

    // Call server action
    return await addAgent(
      {
        message: "",
        errors: {},
        fieldValues: {
          name: "",
          description: "",
          instruction: "",
          model_id: "",
          tools_config: { mcp_server_configs: [] },
          events_config: { events: [] },
          planning: false,
        },
      },
      formData
    );
  };

  const handleSuccess = (result: any) => {
    const createdId = (result.fieldValues as any)?.id;
    if (createdId && result.fieldValues) {
      router.push(`/agents/${createdId}`);
    }
  };

  return (
    <AgentForm
      mcpServers={mcpServers}
      llmModelInstances={llmModelInstances}
      mcpInstanceList={mcpInstanceList}
      builtinTools={builtinTools}
      initialData={{
        name: generateAgentName(),
        description: "",
        instruction: "",
        model_id: "",
        tools_config: { mcp_server_configs: [], builtin_tools: [] },
        events_config: { events: [] },
        planning: false,
      }}
      onSubmit={handleSubmit}
      submitButtonText="Create Agent"
      submitButtonLoadingText="Creating..."
      onSuccess={handleSuccess}
      isLoading={false}
    />
  );
}
