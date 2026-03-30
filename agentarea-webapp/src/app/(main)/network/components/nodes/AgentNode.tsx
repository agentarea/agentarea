"use client";

import { Handle, Position, type NodeProps } from "@xyflow/react";
import { AvatarCircles } from "@/components/ui/avatar-circles";
import { Badge } from "@/components/ui/badge";
import { Card } from "@/components/ui/card";
import ModelBadge from "@/components/ui/model-badge";
import { cn } from "@/lib/utils";
import { getToolAvatarUrlsFromConfig } from "@/utils/toolsDisplay";

export default function AgentNode({ data }: NodeProps) {
  const d = data as Record<string, any>;

  const name = d.label || "Unnamed Agent";
  const modelInfo = d.metadata?.model_info;
  const toolsConfig = d.metadata?.tools_config;
  const skills = d.metadata?.skills;

  const toolAvatars = getToolAvatarUrlsFromConfig(toolsConfig);
  const hasTools = toolAvatars.length > 0;
  const hasSkills = skills && Array.isArray(skills) && skills.length > 0;

  const skillAvatars = hasSkills
    ? skills.slice(0, 3).map((skill: any) => ({
        imageUrl: `https://ui-avatars.com/api/?name=${encodeURIComponent(skill.name || skill.id)}&background=random&size=40&bold=true`,
      }))
    : [];

  const toolsOverflow = toolAvatars.length > 3 ? toolAvatars.length - 3 : 0;
  const skillsOverflow = hasSkills && skills.length > 3 ? skills.length - 3 : 0;

  return (
    <div className="min-w-[220px] max-w-[260px]">
      <Card
        className={cn(
          "group relative flex cursor-pointer overflow-hidden transition-all duration-300",
          "border border-zinc-200 dark:border-zinc-800",
          "bg-white dark:bg-zinc-900",
          "hover:shadow-lg hover:shadow-zinc-200/50 dark:hover:shadow-zinc-950/50",
          "hover:border-primary/20 dark:hover:border-primary/40",
          "hover:-translate-y-0.5",
          "active:scale-[0.99] p-3"
        )}
      >
        <Handle
          type="target"
          position={Position.Left}
          className="!bg-zinc-300 dark:!bg-zinc-600 !w-1.5 !h-1.5 !border-0 !left-0"
        />

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

        <div className="relative z-10 flex items-stretch w-full pr-2">
          <div className="flex-[3] min-w-0 flex flex-col justify-center">
            <h3 className="truncate text-[13px] font-medium leading-tight tracking-tight text-zinc-900 transition-colors duration-300 group-hover:text-primary dark:text-zinc-100 dark:group-hover:text-zinc-50">
              {name}
            </h3>
            <div className="mt-0.5 flex flex-wrap items-center gap-1">
              <ModelBadge
                providerName={modelInfo?.provider_name}
                modelDisplayName={modelInfo?.model_display_name}
                configName={modelInfo?.config_name}
                size="sm"
              />
            </div>
          </div>

          {(hasTools || hasSkills) && (
            <div className="flex items-stretch">
              <div className="relative w-[1px] self-stretch mx-0.5">
                <div className="absolute inset-y-0 left-1/2 w-[1px] -translate-x-1/2 bg-slate-200 dark:bg-slate-600" />
              </div>

              <div className="flex-[2] flex flex-col justify-center gap-0.5 pl-1">
                {hasTools && (
                  <div>
                    <p className="text-[8px] font-medium text-muted-foreground mb-0.5">
                      Tools
                    </p>
                    <div className="flex items-center gap-0.5">
                      <AvatarCircles maxDisplay={3} avatarUrls={toolAvatars} />
                      {toolsOverflow > 0 && (
                        <Badge
                          variant="secondary"
                          className="text-[7px] px-0.5 py-0 h-3"
                        >
                          +{toolsOverflow}
                        </Badge>
                      )}
                    </div>
                  </div>
                )}

                {hasSkills && (
                  <div>
                    <p className="text-[8px] font-medium text-muted-foreground mb-0.5">
                      Skills
                    </p>
                    <div className="flex items-center gap-0.5">
                      <AvatarCircles maxDisplay={3} avatarUrls={skillAvatars} />
                      {skillsOverflow > 0 && (
                        <Badge
                          variant="secondary"
                          className="text-[7px] px-0.5 py-0 h-3"
                        >
                          +{skillsOverflow}
                        </Badge>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </div>
          )}
        </div>

        <Handle
          type="source"
          position={Position.Right}
          className="!bg-zinc-300 dark:!bg-zinc-600 !w-1.5 !h-1.5 !border-0 !right-0"
        />
      </Card>
    </div>
  );
}
