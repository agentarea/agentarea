"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import type { components } from "@/api/schema";
import type { AgentFormValues } from "../../create/types";
import AgentForm from "../../shared/AgentForm";
import { updateAgentSettings } from "./actions";

type MCPServer = components["schemas"]["MCPServerResponse"];
type LLMModelInstance = components["schemas"]["ModelInstanceResponse"];
type Agent =
  components["schemas"]["agentarea_api__api__v1__agents__AgentResponse"];

interface AgentEditClientProps {
  agentId: string;
  agent: Agent;
  mcpServers: MCPServer[];
  llmModelInstances: LLMModelInstance[];
  mcpInstanceList: any[];
  builtinTools: any[];
  initialData: Partial<AgentFormValues>;
}

export default function AgentEditClient({
  agentId,
  agent,
  mcpServers,
  llmModelInstances,
  mcpInstanceList,
  builtinTools,
  initialData,
}: AgentEditClientProps) {
  const router = useRouter();

  const handleSubmit = async (formData: AgentFormValues) => {
    try {
      // Call server action instead of direct API call
      const updateData: any = {
        name: formData.name,
        description: formData.description || undefined,
        instruction: formData.instruction,
        model_id: formData.model_id,
        tools_config: {
          mcp_server_configs: formData.tools_config.mcp_server_configs,
        },
        events_config: {
          events: formData.events_config.events,
        },
        planning: formData.planning,
      };

      const { data, error } = await updateAgentSettings(agentId, updateData);

      if (error) {
        console.error("Update error:", error);
        toast.error("Failed to update agent");
        return {
          message: "Failed to update agent",
          errors: { _form: ["Failed to update agent"] },
        };
      }

      if (data) {
        toast.success("Agent updated successfully!");
        router.refresh();
        return {
          message: "Agent updated successfully!",
        };
      }

      return {
        message: "Unknown error",
        errors: { _form: ["Unknown error"] },
      };
    } catch (err) {
      console.error("Unexpected error:", err);
      toast.error("Unexpected error occurred");
      return {
        message: "Unexpected error occurred",
        errors: { _form: ["Unexpected error occurred"] },
      };
    }
  };

  return (
    <AgentForm
      mcpServers={mcpServers}
      llmModelInstances={llmModelInstances}
      mcpInstanceList={mcpInstanceList}
      builtinTools={builtinTools}
      initialData={initialData}
      onSubmit={handleSubmit}
      submitButtonText="Save Changes"
      submitButtonLoadingText="Saving..."
      isLoading={false}
    />
  );
}
