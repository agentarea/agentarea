"use client";

import { Info, Pencil, Plus } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { PolicyRule } from "@/types/policies";
import { EFFECT_STYLES } from "./policy-effects";

function RuleRow({ rule }: { rule: PolicyRule }) {
  const style = EFFECT_STYLES[rule.effect];
  return (
    <div className="flex items-center gap-3 px-4 py-2.5 text-sm">
      <span className={cn("h-1.5 w-1.5 shrink-0 rounded-full", style.dot)} aria-hidden />
      <span className={cn("shrink-0 rounded px-1.5 py-0.5 text-[11px] font-medium", style.chip)}>
        {rule.category}
      </span>
      <span className="text-foreground">{rule.label}</span>
      <span className="ml-auto truncate font-mono text-xs text-muted-foreground" title={rule.value}>
        {rule.value}
      </span>
    </div>
  );
}

function RulesBlock({ rules, emptyText }: { rules: PolicyRule[]; emptyText: string }) {
  if (rules.length === 0) {
    return <div className="px-4 py-3 text-sm text-muted-foreground">{emptyText}</div>;
  }
  return <div className="divide-y divide-border/60">{rules.map((r, i) => <RuleRow key={`${r.category}-${r.label}-${i}`} rule={r} />)}</div>;
}

export interface ConfiguredPolicyCard {
  id: string;
  title: string;
  enabled: boolean;
  rules: PolicyRule[];
}

export function PolicyRulesView({
  baseline,
  policies,
  hasWorkspacePolicy,
  onEdit,
  onSetWorkspacePolicy,
}: {
  baseline: PolicyRule[];
  policies: ConfiguredPolicyCard[];
  hasWorkspacePolicy: boolean;
  onEdit: (policyId: string) => void;
  onSetWorkspacePolicy: () => void;
}) {
  return (
    <div className="space-y-5">
      {/* Workspace baseline — always present (synthetic, read-only) */}
      <section className="overflow-hidden rounded-lg border border-border">
        <header className="flex items-center gap-2 border-b border-border/60 bg-muted/40 px-4 py-2.5">
          <span className="text-sm font-semibold">Workspace defaults</span>
          <Badge variant="secondary" className="text-[11px]">effective</Badge>
          <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground">
            <Info className="h-3.5 w-3.5" />
            resolved baseline · read-only
          </span>
        </header>
        <RulesBlock
          rules={baseline}
          emptyText="No active restrictions — agents run unrestricted in this workspace."
        />
        {!hasWorkspacePolicy && (
          <div className="flex items-center justify-end border-t border-border/60 px-4 py-2.5">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-1.5"
              onClick={onSetWorkspacePolicy}
            >
              <Plus className="h-3.5 w-3.5" />
              Set workspace policy
            </Button>
          </div>
        )}
      </section>

      {policies.length > 0 && (
        <section className="space-y-3">
          <h3 className="px-1 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
            Configured policies · {policies.length}
          </h3>
          {policies.map((p) => (
            <button
              key={p.id}
              type="button"
              onClick={() => onEdit(p.id)}
              className="group w-full overflow-hidden rounded-lg border border-border text-left transition-colors hover:border-primary/40"
            >
              <header className="flex items-center gap-2 border-b border-border/60 px-4 py-2.5">
                <span className="text-sm font-semibold">{p.title}</span>
                <Badge variant={p.enabled ? "success" : "secondary"} className="text-[11px]">
                  {p.enabled ? "enabled" : "disabled"}
                </Badge>
                <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                  <Pencil className="h-3.5 w-3.5" />
                  Edit
                </span>
              </header>
              <RulesBlock rules={p.rules} emptyText="No restrictions defined in this policy." />
            </button>
          ))}
        </section>
      )}
    </div>
  );
}
