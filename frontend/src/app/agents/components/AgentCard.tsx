import { Agent } from "@/types";
import { AvatarCircles } from "@/components/ui/avatar-circles";
import { ArrowRight } from "lucide-react";
import ModelBadge from "@/components/ui/model-badge";
import { getToolAvatarUrls } from "@/utils/toolsDisplay";

type AgentCardProps = {
  agent: Agent;
}

export default function AgentCard({ agent }: AgentCardProps) {
    console.log(agent);

    return (
        <div className="flex flex-col justify-between gap-6 h-full">
            <div className="flex flex-col gap-2 px-[16px] md:px-[20px] lg:px-[24px]">
                <div className="flex items-start gap-3 justify-between">
                    <div className="flex items-center gap-3">
                        {agent.icon && (
                            <img 
                                src={agent.icon} 
                                alt={`${agent.name} icon`} 
                                className="w-8 h-8 rounded dark:invert"
                            />
                        )}
                        <div className="flex flex-col">
                            <h3>
                                {agent.name}
                            </h3>
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
                <p className="text-xs text-muted-foreground mt-1 line-clamp-2">
                    {agent.description || agent.instruction}
                </p>
            </div>

            <div className="
                px-[16px] md:px-[20px] lg:px-[24px] 
                py-[10px]
                group-hover:bg-zinc-100/70 dark:group-hover:bg-zinc-700/80
                transition-colors duration-300
                border-t border-zinc-200 dark:border-zinc-700
                flex items-center justify-between
"
            >
                {(() => {
                    const toolAvatars = getToolAvatarUrls(agent);
                    return toolAvatars.length > 0 ? (
                        <AvatarCircles
                            maxDisplay={5}
                            avatarUrls={toolAvatars}
                        />
                    ) : (
                        <span className="text-xs text-muted-foreground">No tools</span>
                    );
                })()}
                <div className="small-link text-muted-foreground/70 group-hover:text-primary">
                    View agent
                    <ArrowRight className="h-4 w-4" />
                </div>
            </div>
        </div>
    );
}
