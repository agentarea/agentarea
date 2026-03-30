import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { Loader2 } from "lucide-react";
import ToolsDisplay from "@/components/ToolsDisplay";
import { Badge } from "@/components/ui/badge";
import ModelBadge from "@/components/ui/model-badge";
import {
  getAgentAction as getAgent,
  listModelInstancesAction as listModelInstances,
} from "@/lib/server-actions";
import { Agent } from "@/types/agent";
import { Task } from "../types";
import ActionLink from "./ActionLink";
import ExpandableText from "./ExpandableText";
import Section from "./Section";

interface ModelInfoProps {
  task?: Task | null;
  agentId?: string;
}

export default function ModelInfo({ task, agentId }: ModelInfoProps) {
  const t = useTranslations("TaskInfoPanel");
  const [agent, setAgent] = useState<Agent | null>(null);
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

    if (targetAgentId) {
      fetchAgent();
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

  const validTriggers =
    agent.events_config?.events?.filter((e: any) => e.event_type) || [];

  return (
    <Section title={t("agentInfo")} contentClassName="space-y-4 text-xs">
      {/* Agent Name */}
      <div className="space-y-1.5">
        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {t("agent")}
        </div>
        <div className="text-sm font-semibold text-foreground">
          {agent.name}
        </div>
      </div>

      {/* Model */}
      <div className="space-y-1.5">
        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {t("model")}
        </div>
        <div>
          <ModelBadge
            providerName={agent.model_info?.provider_name}
            modelDisplayName={agent.model_info?.model_display_name}
            configName={agent.model_info?.config_name}
          />
        </div>
      </div>

      {/* Description / Goal */}
      {agent.description && agent.description.trim().length > 0 && (
        <div className="space-y-1.5">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            {t("descriptionGoal")}
          </div>
          <ExpandableText content={agent.description} />
        </div>
      )}

      {/* Instruction */}
      {agent.instruction && agent.instruction.trim().length > 0 && (
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
            {validTriggers.map((event: any, index: number) => (
              <Badge
                key={index}
                variant="outline"
                className="text-[10px] font-normal px-2 py-0.5 h-auto"
              >
                {event.event_type}
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
      <div className="pt-2">
        <ActionLink href={`/agents/${targetAgentId}`}>
          {t("openFullAgentDetails")}
        </ActionLink>
      </div>
    </Section>
  );
}
