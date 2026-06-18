import type { ReactNode } from "react";
import { AgentAvatar, type AgentAvatarAgent } from "@/components/AgentAvatar";
import { cn } from "@/lib/utils";

interface AgentIdentityProps {
  agent: AgentAvatarAgent;
  size?: "xs" | "sm" | "md";
  meta?: string | null;
  right?: ReactNode;
  className?: string;
}

const AVATAR_SIZE: Record<
  NonNullable<AgentIdentityProps["size"]>,
  "xs" | "sm" | "md"
> = {
  xs: "xs",
  sm: "sm",
  md: "md",
};

export function AgentIdentity({
  agent,
  size = "sm",
  meta,
  right,
  className,
}: AgentIdentityProps) {
  return (
    <div className={cn("flex min-w-0 items-center gap-2", className)}>
      <AgentAvatar agent={agent} size={AVATAR_SIZE[size]} />
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-foreground">
          {agent.name || agent.id}
        </div>
        {meta && (
          <div className="truncate text-xs text-muted-foreground">{meta}</div>
        )}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}
