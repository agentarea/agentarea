"use client";

import type { McpServerResponse, McpServerInstanceResponse, ModelInstanceResponse } from "@/api/client/types.gen";
import React from "react";
import { useRouter } from "next/navigation";
import AgentForm from "../shared/AgentForm";
import { addAgent, type AddAgentFormState } from "./actions";
import type { AgentFormValues } from "./types";
import { generateAgentName } from "./utils/agentNameGenerator";

type MCPServer = McpServerResponse;
type LLMModelInstance = ModelInstanceResponse;

export default function CreateAgentClient({
  mcpServers,
  llmModelInstances,
  mcpInstanceList,
  builtinTools,
}: {
  mcpServers: MCPServer[];
  llmModelInstances: LLMModelInstance[];
  mcpInstanceList: McpServerInstanceResponse[];
  builtinTools: unknown[];
}) {
  const router = useRouter();

  const handleSubmit = async (data: AgentFormValues) => {
    // RHF already holds a typed object — pass it straight to the server action.
    // No FormData serialization/reconstruction round-trip.
    return await addAgent(data);
  };

  const handleSuccess = (result: AddAgentFormState) => {
    const createdRef = result.fieldValues?.id;
    if (createdRef) {
      router.push(`/agents/${createdRef}`);
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
        tools_config: { mcp_server_configs: [], builtin_tools: [], openapi_configs: [] },
        events_config: { events: [] },
        planning: false,
        skills: [],
      }}
      onSubmit={handleSubmit}
      submitButtonText="Create Agent"
      submitButtonLoadingText="Creating..."
      onSuccess={handleSuccess}
      isLoading={false}
    />
  );
}
