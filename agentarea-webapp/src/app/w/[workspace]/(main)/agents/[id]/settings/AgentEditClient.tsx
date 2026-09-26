"use client";

import type {
  McpServerInstanceResponse,
  McpServerResponse,
  ModelInstanceResponse,
} from "@/api/client/types.gen";
import { useTranslations } from "next-intl";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { Sparkles } from "lucide-react";
import { ChatWelcome } from "@/components/Chat/componets/ChatWelcome";
import type { AgentFormValues } from "../../create/types";
import AgentForm from "../../shared/AgentForm";
import { updateAgentSettings } from "./actions";

type MCPServer = McpServerResponse;
type LLMModelInstance = ModelInstanceResponse;

interface AgentEditClientProps {
  agentId: string;
  agentName: string;
  mcpServers: MCPServer[];
  llmModelInstances: LLMModelInstance[];
  mcpInstanceList: McpServerInstanceResponse[];
  builtinTools: unknown[];
  initialData: Partial<AgentFormValues>;
}

export default function AgentEditClient({
  agentId,
  agentName,
  mcpServers,
  llmModelInstances,
  mcpInstanceList,
  builtinTools,
  initialData,
}: AgentEditClientProps) {
  const router = useWorkspaceRouter();

  const handleSubmit = async (formData: AgentFormValues) => {
    const result = await updateAgentSettings(agentId, formData);
    if (!result.errors) {
      // Refresh layout to update agent name in breadcrumb
      router.refresh();
    }
    return result;
  };

  const t = useTranslations("AgentsPage.descriptionPage");

  const welcomeComponent = (
    <ChatWelcome
      icon={Sparkles}
      variant="neutral"
      size="sm"
      animate={false}
      titleClassName="text-muted-foreground opacity-70"
      title={t("titleNewTask", { agentName })}
    />
  );

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
      placeholder={t("placeholderNewTask", { agentName })}
      welcomeComponent={welcomeComponent}
    />
  );
}
