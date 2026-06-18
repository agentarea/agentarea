"use client";

import {
  CalendarClock,
  Cable,
  GitFork,
  User,
  Webhook,
  Zap,
} from "lucide-react";
import type { ComponentType, SVGProps } from "react";
import {
  DiscordIcon,
  GmailIcon,
  SlackIcon,
  TelegramIcon,
} from "@/components/brand-icons";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { getTaskSource, type TaskSourceKind } from "@/lib/taskSource";

type IconComponent = ComponentType<SVGProps<SVGSVGElement> & { className?: string }>;

interface TaskSourceBadgeProps {
  parameters?: Record<string, unknown> | null;
  size?: "default" | "sm";
  className?: string;
}

const kindStyle: Record<
  TaskSourceKind,
  { icon: IconComponent; variant: Parameters<typeof Badge>[0]["variant"] }
> = {
  telegram: { icon: TelegramIcon, variant: "blue" },
  email: { icon: GmailIcon, variant: "rose" },
  slack: { icon: SlackIcon, variant: "sky" },
  discord: { icon: DiscordIcon, variant: "blue" },
  channel: { icon: Cable, variant: "teal" },
  delegation: { icon: GitFork, variant: "default" },
  schedule: { icon: CalendarClock, variant: "amber" },
  webhook: { icon: Webhook, variant: "orange" },
  trigger: { icon: Zap, variant: "yellow" },
  a2a: { icon: Cable, variant: "teal" },
  manual: { icon: User, variant: "light" },
};

export function TaskSourceBadge({
  parameters,
  size = "sm",
  className,
}: TaskSourceBadgeProps) {
  const source = getTaskSource(parameters ?? undefined);
  const { icon: Icon, variant } = kindStyle[source.kind];

  const badge = (
    <Badge
      variant={variant}
      size={size}
      className={className}
    >
      <Icon className="h-3 w-3 shrink-0" />
      <span className="truncate max-w-[140px]">
        {source.detail || source.label}
      </span>
    </Badge>
  );

  if (!source.detail) {
    return badge;
  }

  return (
    <TooltipProvider delayDuration={150}>
      <Tooltip>
        <TooltipTrigger asChild>
          <span className="inline-flex">{badge}</span>
        </TooltipTrigger>
        <TooltipContent>
          <span className="font-medium">{source.label}</span>
          <span className="opacity-70"> · {source.detail}</span>
        </TooltipContent>
      </Tooltip>
    </TooltipProvider>
  );
}
