import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";
import ToolsDisplay from "@/components/ToolsDisplay";
import { Badge } from "@/components/ui/badge";
import ModelBadge from "@/components/ui/model-badge";
import {
  getAgentAction as getAgent,
  listModelInstancesAction as listModelInstances,
  listTriggersAction as listTriggers,
} from "@/lib/server-actions";
import { cn } from "@/lib/utils";
import { Agent } from "@/types/agent";
import { Task } from "../types";
import ActionLink from "./ActionLink";
import ExpandableText from "./ExpandableText";
import ModelPicker from "./ModelPicker";
import Section from "./Section";

interface ModelInfoProps {
  task?: Task | null;
  agentId?: string;
  isActive?: boolean;
  hideAgentHeader?: boolean;
  hideDescription?: boolean;
  hideInstruction?: boolean;
  hideOpenButton?: boolean;
}

export default function ModelInfo({
  task,
  agentId,
  isActive = false,
  hideAgentHeader = false,
  hideDescription = false,
  hideInstruction = false,
  hideOpenButton = false,
}: ModelInfoProps) {
  const t = useTranslations("TaskInfoPanel");
  const [agent, setAgent] = useState<Agent | null>(null);
  const [triggers, setTriggers] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);

  const targetAgentId = task?.agent_id || agentId;

  useEffect(() => {
    const fetchAgent = async () => {
      if (!targetAgentId) return;

      try {
        setLoading(true);
        const { data } = await getAgent(targetAgentId);
        const agentData = data as Agent;

        if (agentData) {
          // If model_info is missing but model_id exists, try to fetch model info
          if (!agentData.model_info && agentData.model_id) {
            try {
              const { data: instances } = await listModelInstances();
              const model = instances?.find(
                (m: any) => m.id === agentData.model_id
              );

              if (model) {
                agentData.model_info = {
                  provider_name: model.provider_name || undefined,
                  provider_icon_url: model.provider_icon_url || undefined,
                  model_display_name: model.model_display_name || undefined,
                  config_name: model.config_name || undefined,
                };
              }
            } catch (err) {
              console.warn("Failed to fetch model info", err);
            }
          }
          setAgent(agentData as Agent);
        }
      } catch (error) {
        console.error("Failed to fetch agent details:", error);
      } finally {
        setLoading(false);
      }
    };

    const fetchTriggers = async () => {
      if (!targetAgentId) return;
      try {
        const { data } = await listTriggers({ agent_id: targetAgentId });
        const items = Array.isArray(data) ? data : (data as any)?.items || [];
        setTriggers(Array.isArray(items) ? items : []);
      } catch (error) {
        console.warn("Failed to fetch triggers", error);
        setTriggers([]);
      }
    };

    if (targetAgentId) {
      fetchAgent();
      fetchTriggers();
    }
  }, [targetAgentId]);

  if (loading) {
    return (
      <Section title={t("agentInfo")}>
        <div className="flex justify-center py-4">
          <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
        </div>
      </Section>
    );
  }

  if (!agent) {
    return (
      <Section title={t("agentInfo")}>
        <div className="text-xs text-muted-foreground">
          {t("failedToLoadAgent")}
        </div>
      </Section>
    );
  }

  // Triggers come from the canonical Triggers API (filtered by agent), not the
  // agent's embedded events_config — the latter does not reflect the real
  // triggers and showed stale/incorrect entries.
  const validTriggers = triggers.filter((tr) => tr && (tr.name || tr.id));

  return (
    <Section title={t("agentInfo")} contentClassName="space-y-4 text-xs">
      {/* Agent Name */}
      {!hideAgentHeader && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {t("agent")}
          </div>
          <div className="text-sm font-semibold text-foreground">
            {agent.name}
          </div>
        </div>
      )}

      {/* Model */}
      <div className="space-y-1.5">
        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {t("model")}
        </div>
        <div>
          <ModelBadge
            providerName={agent.model_info?.provider_name}
            iconUrl={agent.model_info?.provider_icon_url}
            modelDisplayName={agent.model_info?.model_display_name}
            configName={agent.model_info?.config_name}
          />
        </div>
        {task && (
          <ModelPicker
            agentId={task.agent_id}
            taskId={task.id}
            currentModelId={agent.model_id ?? undefined}
            isActive={isActive}
          />
        )}
      </div>

      {/* Description / Goal */}
      {agent.description &&
        agent.description.trim().length > 0 &&
        !hideDescription && (
          <div className="space-y-1.5">
            <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {t("descriptionGoal")}
            </div>
            <ExpandableText content={agent.description} />
          </div>
        )}

      {/* Instruction */}
      {agent.instruction &&
        agent.instruction.trim().length > 0 &&
        !hideInstruction && (
          <div className="space-y-1.5">
            <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {t("instruction")}
            </div>
            <ExpandableText content={agent.instruction} />
          </div>
        )}

      {/* Triggers */}
      {validTriggers.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {t("triggers")}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {validTriggers.map((tr: any, index: number) => (
              <Badge
                key={tr.id ?? index}
                variant="outline"
                className={cn(
                  "h-auto px-2 py-0.5 text-[10px] font-normal",
                  tr.is_active === false && "opacity-50"
                )}
                title={tr.description || tr.trigger_type || undefined}
              >
                {tr.name || tr.trigger_type || tr.id}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Tools */}
      <div className="space-y-1.5">
        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {t("tools")}
        </div>
        <div>
          <ToolsDisplay agent={agent} />
        </div>
      </div>

      {/* Skills */}
      {agent.skills && agent.skills.length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {t("skills")}
          </div>
          <div className="flex flex-wrap gap-1.5">
            {agent.skills.map((skill) => (
              <Badge
                key={skill.id}
                variant="secondary"
                className="text-[10px] font-normal px-2 py-0.5 h-auto bg-purple-50 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300 hover:bg-purple-100 dark:hover:bg-purple-900/50 border-purple-200 dark:border-purple-800"
              >
                {skill.name}
              </Badge>
            ))}
          </div>
        </div>
      )}

      {/* Link to full details */}
      {!hideOpenButton && (
        <div className="pt-2">
          <ActionLink href={`/agents/${targetAgentId}`}>
            {t("openFullAgentDetails")}
          </ActionLink>
        </div>
      )}
    </Section>
  );
}
