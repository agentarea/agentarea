import { createElement } from "react";
import {
  agentColorVar,
  agentColorVarSoft,
  getAgentIconComponent,
  resolveAgentIdentity,
  type AgentColorToken,
} from "@/lib/agent-identity";
import { cn } from "@/lib/utils";

export type AgentAvatarAgent = {
  id: string;
  name?: string | null;
  icon?: string | null;
  color_token?: string | null;
};

type AgentAvatarProps = {
  agent: AgentAvatarAgent;
  size?: "xs" | "sm" | "md" | "lg";
  className?: string;
  status?: "idle" | "running" | "hitl" | "error" | "paused" | null;
};

const SIZE_CLASS: Record<NonNullable<AgentAvatarProps["size"]>, string> = {
  xs: "h-5 w-5 [&>svg]:h-3 [&>svg]:w-3",
  sm: "h-6 w-6 [&>svg]:h-3.5 [&>svg]:w-3.5",
  md: "h-9 w-9 [&>svg]:h-[18px] [&>svg]:w-[18px]",
  lg: "h-12 w-12 [&>svg]:h-6 [&>svg]:w-6",
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

export function AgentAvatar({
  agent,
  size = "sm",
  className,
  status,
}: AgentAvatarProps) {
  const { colorToken, iconKey } = resolveAgentIdentity(agent);
  const sizeCls = SIZE_CLASS[size];

  return (
    <span className={cn("relative inline-flex shrink-0", className)}>
      <span
        className={cn(
          "inline-flex items-center justify-center rounded-md",
          sizeCls
        )}
        style={
          {
            color: agentColorVar(colorToken as AgentColorToken),
            background: agentColorVarSoft(colorToken as AgentColorToken, 0.14),
          } as React.CSSProperties
        }
        aria-hidden="true"
      >
        {createElement(getAgentIconComponent(iconKey), { strokeWidth: 2 })}
      </span>
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
  agent: AgentAvatarProps["agent"];
  className?: string;
}) {
  const { colorToken } = resolveAgentIdentity(agent);
  return (
    <span
      className={cn("inline-block w-1 self-stretch rounded-full", className)}
      style={{ background: agentColorVar(colorToken as AgentColorToken) }}
      aria-hidden="true"
    />
  );
}
