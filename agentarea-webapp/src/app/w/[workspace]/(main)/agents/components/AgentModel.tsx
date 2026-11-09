import { HarnessClientLink } from "@/components/harnesses";
import ModelBadge from "@/components/ui/model-badge";
import { withReasoning } from "@/lib/runner-models";
import { cn } from "@/lib/utils";
import type { Agent } from "@/types";

/** The model an agent runs with, or the client it runs on with that client's model. */
export function AgentModel({
  agent,
  className,
}: {
  agent: Pick<Agent, "client" | "model_info" | "reasoning_effort">;
  className?: string;
}) {
  if (agent.client) {
    return (
      <span
        className={cn(
          "flex min-w-0 max-w-full items-center gap-1.5 text-xs",
          className
        )}
      >
        <HarnessClientLink
          client={agent.client}
          className="relative z-30 font-medium"
        />
        {agent.client.default_model && (
          <span className="truncate text-muted-foreground">
            {withReasoning(agent.client.default_model, agent.reasoning_effort)}
          </span>
        )}
      </span>
    );
  }
  return (
    <ModelBadge
      className={className}
      providerName={agent.model_info?.provider_name}
      iconUrl={agent.model_info?.provider_icon_url}
      modelDisplayName={agent.model_info?.model_display_name}
      configName={agent.model_info?.config_name}
    />
  );
}
