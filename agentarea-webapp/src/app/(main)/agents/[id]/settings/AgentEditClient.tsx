"use client";

import { useRouter } from "next/navigation";
import { toast } from "sonner";
import type { components } from "@/api/schema";
import type { AgentFormValues } from "../../create/types";
import AgentForm from "../../shared/AgentForm";
import { updateAgentSettings } from "./actions";

type MCPServer = components["schemas"]["MCPServerResponse"];
type LLMModelInstance = components["schemas"]["ModelInstanceResponse"];

interface AgentEditClientProps {
  agentId: string;
  mcpServers: MCPServer[];
  llmModelInstances: LLMModelInstance[];
  mcpInstanceList: any[];
  builtinTools: any[];
  initialData: Partial<AgentFormValues>;
}

export default function AgentEditClient({
  agentId,
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
      // Transform form tools_config into backend tools format
      const tools: any[] = [];

      // MCP tools
      for (const mcpConfig of formData.tools_config.mcp_server_configs || []) {
        const allowedToolNames = (mcpConfig.allowed_tools || []).map((t: any) => t.tool_name);
        const toolsRequiringApproval = (mcpConfig.allowed_tools || [])
          .filter((t: any) => t.requires_user_confirmation)
          .map((t: any) => t.tool_name);

        tools.push({
          type: "mcp",
          name: mcpConfig.mcp_server_id,
          settings: {
            mcp_server_id: mcpConfig.mcp_server_id,
            allowed_tools: allowedToolNames.length > 0 ? allowedToolNames : null,
            requires_user_confirmation: toolsRequiringApproval.length > 0 ? true : null,
          },
        });
      }

      // Builtin tools
      for (const bt of (formData.tools_config as any).builtin_tools || []) {
        const disabledMethods = bt.disabled_methods
          ? Object.entries(bt.disabled_methods)
              .filter(([, v]) => v === false)
              .map(([k]) => k)
          : null;

        tools.push({
          type: "code",
          name: bt.tool_name,
          settings: {
            disabled_methods: disabledMethods?.length ? disabledMethods : null,
            requires_user_confirmation: bt.requires_user_confirmation ?? null,
          },
        });
      }

      const updateData: any = {
        name: formData.name,
        description: formData.description || undefined,
        instruction: formData.instruction,
        model_id: formData.model_id,
        tools: tools.length > 0 ? tools : null,
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
        // Refresh layout to update agent name in breadcrumb
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
      className="pl-5"
      mcpServers={mcpServers}
      llmModelInstances={llmModelInstances}
      mcpInstanceList={mcpInstanceList}
      builtinTools={builtinTools}
      initialData={initialData}
      agentId={agentId}
      onSubmit={handleSubmit}
      submitButtonText="Save Changes"
      submitButtonLoadingText="Saving..."
      isLoading={false}
    />
  );
}
