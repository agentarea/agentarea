"use client";

import { useMemo } from "react";
import {
  Coins,
  Settings2,
  ShieldCheck,
  UserCheck,
  Wallet,
  Wrench,
  type LucideIcon,
} from "lucide-react";
import Table from "@/components/Table/Table";
import { cn } from "@/lib/utils";
import type { Policy } from "@/types/policies";
import { policyToRule } from "./policy-rules";

interface AgentOption {
  id: string;
  name: string;
  icon?: string | null;
  color_token?: string | null;
}

const CATEGORY_ICON: Record<string, LucideIcon> = {
  Budget: Wallet,
  Tokens: Coins,
  Tools: Wrench,
  Approval: UserCheck,
  Safety: ShieldCheck,
  Custom: Settings2,
};

interface PolicyRow {
  id: string;
  label: string;
  value: string;
  category: string;
  effect: Policy["effect"];
  subjectLabel: string;
  isWorkspace: boolean;
  enabled: boolean;
}

function subjectOf(
  policy: Policy,
  agentNameById: Map<string, string>
): { label: string; isWorkspace: boolean } {
  if (policy.subject_type === "workspace")
    return { label: "Workspace", isWorkspace: true };
  if (policy.subject_type === "agent")
    return {
      label: agentNameById.get(policy.subject_id) ?? policy.subject_id,
      isWorkspace: false,
    };
  const kind =
    policy.subject_type.charAt(0).toUpperCase() + policy.subject_type.slice(1);
  return { label: `${kind} · ${policy.subject_id}`, isWorkspace: false };
}

// Reuses the shared <Table> (same as /mcp-servers): one row per policy rule.
export default function PoliciesList({
  policies,
  agents,
  onEditRule,
}: {
  policies: Policy[];
  agents: AgentOption[];
  onEditRule: (ruleId: string) => void;
}) {
  const agentNameById = useMemo(
    () => new Map(agents.map((a) => [a.id, a.name])),
    [agents]
  );

  const rows = useMemo<PolicyRow[]>(() => {
    const list = policies
      .filter((p): p is Policy & { id: string } => Boolean(p.id))
      .map((policy) => {
        const rule = policyToRule(policy);
        const subject = subjectOf(policy, agentNameById);
        return {
          id: policy.id,
          label: rule.label,
          value: rule.value,
          category: rule.category,
          effect: policy.effect,
          subjectLabel: subject.label,
          isWorkspace: subject.isWorkspace,
          enabled: policy.enabled,
        };
      });
    list.sort(
      (a, b) =>
        Number(b.isWorkspace) - Number(a.isWorkspace) ||
        a.subjectLabel.localeCompare(b.subjectLabel) ||
        a.label.localeCompare(b.label)
    );
    return list;
  }, [policies, agentNameById]);

  const columns = [
    {
      accessor: "label",
      header: "Policy",
      render: (value: string, item: PolicyRow) => {
        const Icon = CATEGORY_ICON[item.category] ?? Settings2;
        return (
          <div className="flex min-w-0 items-center gap-3">
            <span className="grid h-7 w-7 shrink-0 place-items-center rounded-lg border border-border bg-white dark:bg-zinc-800">
              <Icon
                className="h-[15px] w-[15px] text-muted-foreground"
                strokeWidth={1.8}
              />
            </span>
            <div className="min-w-0">
              <div className="truncate text-[13px] font-medium text-foreground">
                {value}
              </div>
              <div className="truncate text-[11px] text-muted-foreground">
                {item.subjectLabel}
              </div>
            </div>
          </div>
        );
      },
    },
    {
      accessor: "value",
      header: "Value",
      render: (value: string) => (
        <span className="truncate font-mono text-[11.5px] text-muted-foreground/70">
          {value || "—"}
        </span>
      ),
    },
    {
      accessor: "category",
      header: "Category",
      render: (value: string) => (
        <span className="text-[12.5px] text-muted-foreground">{value}</span>
      ),
    },
    {
      accessor: "effect",
      header: "Effect",
      render: (value: string) => (
        <span className="text-[12.5px] capitalize text-foreground/70">
          {value}
        </span>
      ),
    },
    {
      accessor: "status",
      header: "Status",
      render: (_: unknown, item: PolicyRow) => (
        <span
          className={cn(
            "inline-flex w-fit items-center gap-2 text-[12.5px] font-medium",
            item.enabled
              ? "text-emerald-600 dark:text-emerald-400"
              : "text-muted-foreground"
          )}
        >
          <span
            className={cn(
              "h-[7px] w-[7px] rounded-full ring-[3px]",
              item.enabled
                ? "bg-emerald-500 ring-emerald-500/20"
                : "bg-zinc-400 ring-zinc-400/20"
            )}
          />
          {item.enabled ? "Enabled" : "Disabled"}
        </span>
      ),
    },
  ];

  return (
    <Table
      data={rows}
      columns={columns}
      onRowClick={(item: PolicyRow) => onEditRule(item.id)}
    />
  );
}
