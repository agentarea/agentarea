"use client";

import type { MouseEventHandler, ReactNode } from "react";
import Link from "next/link";
import { AgentAvatar, type AgentAvatarAgent } from "@/components/AgentAvatar";
import { cn } from "@/lib/utils";

export interface AgentIdentityProps {
  agent: AgentAvatarAgent;
  size?: "xs" | "sm" | "md";
  meta?: string | null;
  right?: ReactNode;
  className?: string;
  nameClassName?: string;
  metaClassName?: string;
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
  nameClassName,
  metaClassName,
}: AgentIdentityProps) {
  return (
    <div className={cn("flex min-w-0 items-center gap-2", className)}>
      <AgentAvatar agent={agent} size={AVATAR_SIZE[size]} />
      <div className="min-w-0 flex-1">
        <div className={cn("truncate text-sm text-foreground", nameClassName)}>
          {agent.name || agent.id}
        </div>
        {meta && (
          <div
            className={cn(
              "truncate text-xs text-muted-foreground",
              metaClassName
            )}
          >
            {meta}
          </div>
        )}
      </div>
      {right && <div className="shrink-0">{right}</div>}
    </div>
  );
}

export interface AgentLinkProps extends Omit<AgentIdentityProps, "className"> {
  href?: string;
  className?: string;
  identityClassName?: string;
  onClick?: MouseEventHandler<HTMLAnchorElement>;
}

export function AgentLink({
  agent,
  href = `/agents/${agent.id}`,
  className,
  identityClassName,
  nameClassName,
  onClick,
  ...identityProps
}: AgentLinkProps) {
  return (
    <Link
      href={href}
      onClick={onClick}
      className={cn(
        "group/agent inline-flex min-w-0 rounded-sm focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
        className
      )}
    >
      <AgentIdentity
        agent={agent}
        className={cn("w-full", identityClassName)}
        nameClassName={cn(
          "font-medium transition-colors group-hover/agent:text-primary group-hover/agent:underline group-hover/agent:underline-offset-2",
          nameClassName
        )}
        {...identityProps}
      />
    </Link>
  );
}
