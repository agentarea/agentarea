import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { AvatarCircles } from "@/components/ui/avatar-circles";
import { Card } from "@/components/ui/card";
import ModelBadge from "@/components/ui/model-badge";
import { Agent } from "@/types";
import { getToolAvatarUrls } from "@/utils/toolsDisplay";

type AgentCardProps = {
  agent: Agent;
};

export default function AgentCard({ agent }: AgentCardProps) {
  return (
    <Link href={`/agents/${agent.id}/new-task`}>
      <Card className="group flex h-full flex-col justify-between gap-6 px-0 pb-0">
        <div className="flex flex-col gap-2 px-[16px] md:px-[20px] lg:px-[24px]">
          <div className="flex items-start justify-between gap-3">
            <div className="flex items-center gap-3">
              {agent.icon && (
                <img
                  src={agent.icon}
                  alt={`${agent.name} icon`}
                  className="h-8 w-8 rounded dark:invert"
                />
              )}
              <div className="flex flex-col">
                <h3>{agent.name}</h3>
                <div className="mt-2">
                  <ModelBadge
                    providerName={agent.model_info?.provider_name}
                    modelDisplayName={agent.model_info?.model_display_name}
                    configName={agent.model_info?.config_name}
                  />
                </div>
              </div>
            </div>
            {/* <StatusBadge status={agent.status} variant="agent" /> */}
          </div>
          <p className="mt-1 line-clamp-2 text-xs text-muted-foreground">
            {agent.description || agent.instruction}
          </p>
        </div>

        <div className="flex items-center justify-between border-t border-zinc-200 px-[16px] py-[10px] transition-colors duration-300 group-hover:bg-zinc-100/70 dark:border-zinc-700 dark:group-hover:bg-zinc-700/80 md:px-[20px] lg:px-[24px]">
          {(() => {
            const toolAvatars = getToolAvatarUrls(agent);
            return toolAvatars.length > 0 ? (
              <AvatarCircles maxDisplay={5} avatarUrls={toolAvatars} />
            ) : (
              <span className="text-xs text-muted-foreground">No tools</span>
            );
          })()}
          <div className="small-link text-muted-foreground/70 group-hover:text-primary">
            View agent
            <ArrowRight className="h-4 w-4" />
          </div>
        </div>
      </Card>
    </Link>
  );
}
