import Link from "next/link";
import { AvatarCircles } from "@/components/ui/avatar-circles";
import { Card } from "@/components/ui/card";
import { HoverLink } from "@/components/ui/hover-link";
import ModelBadge from "@/components/ui/model-badge";
import { cn } from "@/lib/utils";
import { Agent } from "@/types";
import { getToolAvatarUrls } from "@/utils/toolsDisplay";

type AgentCardProps = {
  agent: Agent;
};

export default function AgentCard({ agent }: AgentCardProps) {
  return (
    <Link href={`/agents/${agent.id}/new-task`}>
      <div className="block h-full">
        <Card
          className={cn(
            "group relative flex h-full cursor-pointer flex-col justify-between overflow-hidden p-0 transition-all duration-300",
            "border border-zinc-200 dark:border-zinc-800",
            "bg-white dark:bg-zinc-900",
            "hover:shadow-lg hover:shadow-zinc-200/50 dark:hover:shadow-zinc-950/50",
            "hover:border-primary/20 dark:hover:border-primary/40",
            "hover:bg-white dark:hover:bg-zinc-800",
            "hover:-translate-y-0.5",
            "active:scale-[0.99]"
          )}
        >
          <div
            className="pointer-events-none absolute inset-0 opacity-[0.015] dark:opacity-[0.03]"
            style={{
              backgroundImage: `repeating-linear-gradient(
                -45deg,
                currentColor,
                currentColor 1px,
                transparent 1px,
                transparent 10px
              )`,
            }}
          />

          <div className="relative z-10 flex h-full flex-col justify-between">
            <div className="flex flex-col gap-2 px-[16px] py-[16px] md:px-[20px] lg:px-[24px]">
              <div className="flex items-start justify-between gap-3">
                <div className="min-w-0 flex-1 pt-0.5">
                  <h3 className="truncate text-[15px] font-medium leading-tight tracking-tight text-zinc-900 transition-colors duration-300 group-hover:text-primary dark:text-zinc-100 dark:group-hover:text-zinc-50">
                    {agent.name}
                  </h3>
                  <div className="mt-1 flex flex-wrap items-center gap-2 text-sm text-muted-foreground">
                    <ModelBadge
                      providerName={agent.model_info?.provider_name}
                      modelDisplayName={agent.model_info?.model_display_name}
                      configName={agent.model_info?.config_name}
                    />
                  </div>
                </div>
              </div>
            </div>

            <div
              className={cn(
                "relative overflow-hidden border-t",
                "border-zinc-200/60 dark:border-zinc-700/60",
                "pl-[16px] pr-[8px] py-[10px] md:pl-[20px] md:pr-[10px] lg:pl-[24px] lg:pr-[10px]",
                "transition-colors duration-500"
              )}
            >
              <div className="pointer-events-none absolute inset-0 bg-white opacity-0 transition-opacity duration-300 group-hover:opacity-100 dark:bg-zinc-800" />
              <div className="relative z-10 flex items-center justify-between">
                {(() => {
                  const toolAvatars = getToolAvatarUrls(agent);
                  return toolAvatars.length > 0 ? (
                    <AvatarCircles maxDisplay={5} avatarUrls={toolAvatars} />
                  ) : (
                    <span className="text-xs text-muted-foreground">No tools</span>
                  );
                })()}
                <HoverLink text="View agent" />
              </div>
            </div>
          </div>
        </Card>
      </div>
    </Link>
  );
}
