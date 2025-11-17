import Link from "next/link";
import { ArrowUpRight } from "lucide-react";
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

        <div className="  
          flex items-center justify-between border-t border-zinc-200 relative
          pl-[16px] pr-[8px] py-[10px] md:pl-[20px] md:pr-[10px] lg:pl-[24px] lg:pr-[10px]
          transition-colors duration-500 
          transition-background-position duration-500
          group-hover:bg-[url('/lines.png')] bg-cover bg-left group-hover:bg-right
          dark:border-zinc-700 dark:group-hover:bg-[url('/lines-dark.png')]
        ">
          {(() => {
            const toolAvatars = getToolAvatarUrls(agent);
            return toolAvatars.length > 0 ? (
              <AvatarCircles maxDisplay={5} avatarUrls={toolAvatars} />
            ) : (
              <span className="text-xs text-muted-foreground">No tools</span>
            );
          })()}
          <div className="small-link text-muted-foreground/70 group-hover:text-primary gap-1">
            <span className="opacity-0 group-hover:opacity-100 transition-opacity duration-500">View agent</span>
            <ArrowUpRight className="h-[18px] w-[18px] group-hover:scale-110 transition-transform duration-500" strokeWidth={1.5} />
          </div>
        </div>
      </Card>
    </Link>
  );
}
