"use client";

import { useTranslations } from "next-intl";
import { type Node, type NodeProps } from "@xyflow/react";
import {
  ArrowDownToLine,
  ArrowUpRight,
  GitBranch,
  Globe,
  HelpCircle,
  LockKeyhole,
} from "lucide-react";
import { cn } from "@/lib/utils";

export interface NetworkRegionData extends Record<string, unknown> {
  kind:
    | "inputs"
    | "agents"
    | "outputs"
    | "agentCluster"
    | "private"
    | "egress"
    | "unknown";
  count: number;
  label?: string;
}

const icons = {
  inputs: ArrowDownToLine,
  agents: GitBranch,
  outputs: ArrowUpRight,
  agentCluster: GitBranch,
  private: LockKeyhole,
  egress: Globe,
  unknown: HelpCircle,
};

export default function NetworkRegion({
  data,
}: NodeProps<Node<NetworkRegionData>>) {
  const t = useTranslations("NetworkPage.flowMap");
  const lane =
    data.kind === "inputs" || data.kind === "agents" || data.kind === "outputs";
  const Icon = icons[data.kind];
  return (
    <section
      aria-hidden="true"
      className={cn(
        "h-full w-full rounded-xl border border-border/70",
        lane ? "bg-background/40" : "border-dashed bg-background/70"
      )}
    >
      <header
        className={cn(
          "px-5 pt-4",
          lane ? "text-foreground" : "text-muted-foreground"
        )}
      >
        <div className="flex items-center gap-2">
          <Icon
            className={cn(
              "h-4 w-4 shrink-0",
              data.kind === "inputs" && "text-amber-600 dark:text-amber-400",
              data.kind === "agents" && "text-primary",
              data.kind === "outputs" &&
                "text-emerald-600 dark:text-emerald-400"
            )}
          />
          <span
            className={cn(
              "min-w-0 flex-1 truncate font-medium",
              lane ? "text-sm" : "text-xs"
            )}
          >
            {data.kind === "agentCluster"
              ? (data.label ??
                t(data.count === 1 ? "independent" : "agentCluster"))
              : t(data.kind)}
          </span>
          <span className="text-xs tabular-nums text-muted-foreground">
            {data.count}
          </span>
        </div>
        {lane && (
          <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
            {t(`${data.kind}Hint`)}
          </p>
        )}
        {lane && data.count === 0 && (
          <p className="mt-6 text-xs leading-5 text-muted-foreground">
            {t(`${data.kind}Empty`)}
          </p>
        )}
      </header>
    </section>
  );
}
