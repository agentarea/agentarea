import { createElement } from "react";
import {
  getAgentIconComponent,
  resolveAgentIdentity,
  type AgentIdentityInput,
} from "@/lib/agent-identity";
import { avatarHueStyle } from "@/lib/avatar-hue";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { cn } from "@/lib/utils";

export type AgentAvatarAgent = AgentIdentityInput;

type AgentAvatarProps = {
  agent: AgentAvatarAgent;
  size?: "xs" | "sm" | "md" | "lg";
  className?: string;
  status?: "idle" | "running" | "hitl" | "error" | "paused" | null;
};

const SIZE_PX: Record<NonNullable<AgentAvatarProps["size"]>, number> = {
  xs: 20,
  sm: 24,
  md: 36,
  lg: 48,
};

const STATUS_CLASS: Record<
  NonNullable<AgentAvatarProps["status"]>,
  { color: string; pulse: boolean }
> = {
  idle: { color: "bg-emerald-500", pulse: false },
  running: { color: "bg-blue-500", pulse: true },
  hitl: { color: "bg-amber-500", pulse: true },
  error: { color: "bg-red-500", pulse: false },
  paused: { color: "bg-zinc-400", pulse: false },
};

/**
 * An agent, wherever one is listed. Graphite rather than pigment on purpose:
 * people are the coloured marks in a list, agents are the neutral ones, and the
 * split is what makes a mixed feed readable at a glance.
 */
export function AgentAvatar({
  agent,
  size = "sm",
  className,
  status,
}: AgentAvatarProps) {
  const { hue, iconKey } = resolveAgentIdentity(agent);
  const px = SIZE_PX[size];

  return (
    <span className={cn("relative inline-flex shrink-0", className)}>
      <EntityAvatar
        size={px}
        hue={hue}
        icon={createElement(getAgentIconComponent(iconKey), {
          strokeWidth: 1.85,
        })}
      />
      {status && (
        <span
          className={cn(
            "absolute -right-0.5 -bottom-0.5 h-2 w-2 rounded-full ring-2 ring-white dark:ring-zinc-800",
            STATUS_CLASS[status].color,
            STATUS_CLASS[status].pulse && "animate-pulse"
          )}
        />
      )}
    </span>
  );
}

export function AgentColorStripe({
  agent,
  className,
}: {
  agent: AgentAvatarAgent;
  className?: string;
}) {
  const { hue } = resolveAgentIdentity(agent);
  return (
    <span
      className={cn(
        "avatar-hue-fill inline-block w-1 self-stretch rounded-full",
        className
      )}
      style={avatarHueStyle(hue)}
      aria-hidden="true"
    />
  );
}
