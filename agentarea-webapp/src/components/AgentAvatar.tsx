import { createElement } from "react";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import {
  StatusIndicator,
  type StatusKind,
} from "@/components/ui/status-indicator";
import {
  getAgentIconComponent,
  resolveAgentIdentity,
  type AgentIdentityInput,
} from "@/lib/agent-identity";
import { avatarHueStyle } from "@/lib/avatar-hue";
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

type Activity = NonNullable<AgentAvatarProps["status"]>;

const STATUS_KIND: Record<Activity, StatusKind> = {
  idle: "active",
  running: "running",
  hitl: "attention",
  error: "failed",
  paused: "paused",
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
        <span className="absolute -right-1 -bottom-1 rounded-full bg-background p-0.5">
          <StatusIndicator
            kind={STATUS_KIND[status]}
            size="sm"
            aria-label={status}
            title={status}
            className="leading-none"
          />
        </span>
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
