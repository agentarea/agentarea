"use client";

import { useMemo, useState } from "react";
import { Pencil, Plus, Search } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetFooter,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  TableBody,
  TableCell,
  Table as TableComponent,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { cn } from "@/lib/utils";
import type { PolicyEffect, PolicyRule } from "@/types/policies";
import { EFFECT_STYLES } from "./policy-effects";
import type {
  MatrixDimension,
  MatrixSubject,
  PolicyMatrix,
} from "./policy-rules";
import { scopeLabel } from "./policy-rules";

interface AgentOption {
  id: string;
  name: string;
}

// Where a new rule should be scoped when added from a subject drawer.
export interface AddRuleScope {
  subjectType: "workspace" | "agent";
  subjectId: string;
}

type ShowFilter = "all" | "gaps";

// Subtle gap signal for risk dimensions a subject does NOT set. Reuses the
// amber palette already in EFFECT_STYLES (approval) so we don't invent a color.
const GAP_DASH = "text-amber-600 dark:text-amber-400";

const COLUMN_COUNT = 8;

// A subject "has a gap" when it lacks a budget cap or an approval requirement —
// the two risk dimensions an admin most wants to catch.
function hasGap(subject: MatrixSubject): boolean {
  return (
    subject.dimensions.budget.value === null ||
    subject.dimensions.approval.value === null
  );
}

// Compact value chip colored via the dimension's effect; "—" otherwise. Risk
// dimensions render the dash in amber as a tasteful gap signal.
function DimensionCell({
  dimension,
  isRisk,
  tooltip,
}: {
  dimension: MatrixDimension;
  isRisk?: boolean;
  tooltip?: string;
}) {
  if (dimension.value === null) {
    return (
      <span className={cn("text-sm", isRisk ? GAP_DASH : "text-muted-foreground")}>
        —
      </span>
    );
  }

  const style: PolicyEffect | null = dimension.effect;
  const chipClass = style ? EFFECT_STYLES[style].chip : "bg-muted text-foreground";

  const chip = (
    <span
      className={cn(
        "inline-flex items-center rounded px-1.5 py-0.5 text-[11px] font-medium",
        chipClass
      )}
    >
      {dimension.value}
    </span>
  );

  if (!tooltip) return chip;

  return (
    <Tooltip>
      <TooltipTrigger asChild>{chip}</TooltipTrigger>
      <TooltipContent className="max-w-[220px]">{tooltip}</TooltipContent>
    </Tooltip>
  );
}

// Subject cell. Workspace scope opens a popover listing the agents it inherits
// down to; agent scope shows a plain "Agent · <name>".
function SubjectCell({
  subject,
  agents,
}: {
  subject: MatrixSubject;
  agents: AgentOption[];
}) {
  if (subject.subjectType !== "workspace") {
    return (
      <div className="flex flex-col">
        <span className="font-medium text-foreground">{subject.subjectName}</span>
        <span className="text-[11px] text-muted-foreground">Agent</span>
      </div>
    );
  }

  return (
    <div className="flex flex-col">
      <Popover>
        <PopoverTrigger asChild>
          <button
            type="button"
            onClick={(e) => e.stopPropagation()}
            className="text-left font-medium text-foreground underline-offset-4 hover:underline"
          >
            Workspace
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="start"
          className="w-56 p-0"
          onClick={(e) => e.stopPropagation()}
        >
          <div className="border-b border-border/60 px-3 py-2 text-xs font-medium text-muted-foreground">
            Inherited by {agents.length} agent{agents.length === 1 ? "" : "s"}
          </div>
          {agents.length === 0 ? (
            <div className="px-3 py-2 text-sm text-muted-foreground">
              No agents in this workspace.
            </div>
          ) : (
            <ul className="max-h-64 overflow-y-auto py-1">
              {agents.map((agent) => (
                <li key={agent.id} className="px-3 py-1.5 text-sm text-foreground">
                  {agent.name}
                </li>
              ))}
            </ul>
          )}
        </PopoverContent>
      </Popover>
      <span className="text-[11px] text-muted-foreground">
        Workspace · all agents ({agents.length})
      </span>
    </div>
  );
}

function MatrixRow({
  subject,
  agents,
  onOpen,
}: {
  subject: MatrixSubject;
  agents: AgentOption[];
  onOpen: (subject: MatrixSubject) => void;
}) {
  return (
    <TableRow
      onClick={() => onOpen(subject)}
      className="group cursor-pointer border-b border-border/60 transition-colors hover:bg-primary/5 dark:hover:bg-primary/10"
    >
      <TableCell className="py-2.5 first:pl-5">
        <SubjectCell subject={subject} agents={agents} />
      </TableCell>
      <TableCell className="py-2.5">
        <DimensionCell dimension={subject.dimensions.budget} isRisk />
      </TableCell>
      <TableCell className="py-2.5">
        <DimensionCell dimension={subject.dimensions.tokens} />
      </TableCell>
      <TableCell className="py-2.5">
        <DimensionCell
          dimension={subject.dimensions.tools}
          tooltip="Fine-grained tool access lives in the Access view."
        />
      </TableCell>
      <TableCell className="py-2.5">
        <DimensionCell dimension={subject.dimensions.approval} isRisk />
      </TableCell>
      <TableCell className="py-2.5">
        <DimensionCell dimension={subject.dimensions.safety} />
      </TableCell>
      <TableCell className="py-2.5">
        {subject.customCount > 0 ? (
          <Badge variant="amber" size="sm">
            {subject.customCount}
          </Badge>
        ) : (
          <span className="text-sm text-muted-foreground">—</span>
        )}
      </TableCell>
      <TableCell className="py-2.5 last:pr-5">
        <div className="flex items-center gap-2">
          <Badge variant={subject.enabled ? "success" : "disabled"} size="sm">
            {subject.enabled ? "enabled" : "disabled"}
          </Badge>
          <span className="ml-auto flex items-center gap-1 text-xs text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
            Open
          </span>
        </div>
      </TableCell>
    </TableRow>
  );
}

// --- detail drawer --------------------------------------------------------

function EffectChip({ effect }: { effect: PolicyEffect }) {
  const style = EFFECT_STYLES[effect];
  return (
    <span
      className={cn(
        "rounded px-1.5 py-0.5 text-[11px] font-medium",
        style.chip
      )}
    >
      {style.label}
    </span>
  );
}

// Per-subject rule list. Each row is a single backend rule; clicking it edits
// that rule. The footer "Add rule" creates a rule pre-scoped to this subject.
function DetailDrawer({
  subject,
  open,
  onOpenChange,
  onEditRule,
  onAddRule,
}: {
  subject: MatrixSubject | null;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onEditRule: (ruleId: string) => void;
  onAddRule: (scope: AddRuleScope) => void;
}) {
  if (!subject) return null;

  const scope =
    subject.subjectType === "workspace"
      ? "Workspace · inherited by all agents"
      : scopeLabel("agent", subject.subjectName);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="flex w-full flex-col gap-0 p-0 sm:max-w-md"
      >
        <SheetHeader className="border-b border-border px-5 py-4 text-left">
          <SheetTitle className="text-base">{subject.subjectName}</SheetTitle>
          <SheetDescription>{scope}</SheetDescription>
        </SheetHeader>

        <div className="flex-1 space-y-2.5 overflow-y-auto px-5 py-4">
          {subject.rules.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              This subject has no rules yet.
            </p>
          ) : (
            subject.rules.map((rule: PolicyRule) => (
              <button
                key={rule.id}
                type="button"
                onClick={() => rule.id && onEditRule(rule.id)}
                disabled={!rule.id}
                className="group flex w-full flex-col gap-1 rounded-md border border-border/60 px-3 py-2.5 text-left transition-colors hover:border-border hover:bg-muted/40 disabled:cursor-default disabled:hover:bg-transparent"
              >
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <EffectChip effect={rule.effect} />
                  <span className="text-sm text-foreground">{rule.label}</span>
                  <span
                    className="font-mono text-xs text-muted-foreground"
                    title={rule.value}
                  >
                    {rule.value}
                  </span>
                  {rule.enabled === false && (
                    <Badge variant="disabled" size="sm">
                      disabled
                    </Badge>
                  )}
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-[11px] text-muted-foreground">
                    {rule.stage}
                  </span>
                  {rule.id && (
                    <span className="flex items-center gap-1 text-[11px] text-muted-foreground opacity-0 transition-opacity group-hover:opacity-100">
                      <Pencil className="h-3 w-3" />
                      Edit
                    </span>
                  )}
                </div>
              </button>
            ))
          )}
        </div>

        <SheetFooter className="flex-row items-center justify-between gap-2 border-t border-border px-5 py-4">
          <Badge variant={subject.enabled ? "success" : "disabled"} size="sm">
            {subject.enabled ? "enabled" : "disabled"}
          </Badge>
          <Button
            type="button"
            size="sm"
            className="gap-1.5"
            onClick={() =>
              onAddRule({
                subjectType: subject.subjectType,
                subjectId: subject.subjectId,
              })
            }
          >
            <Plus className="h-3.5 w-3.5" />
            Add rule
          </Button>
        </SheetFooter>
      </SheetContent>
    </Sheet>
  );
}

// --- risk summary strip ---------------------------------------------------

function RiskStrip({ matrix }: { matrix: PolicyMatrix }) {
  const stats: { label: string; gap?: boolean }[] = [
    { label: `${matrix.governedCount} governed` },
    { label: `${matrix.noBudgetCapCount} no budget cap`, gap: matrix.noBudgetCapCount > 0 },
    { label: `${matrix.noApprovalCount} no approval`, gap: matrix.noApprovalCount > 0 },
    {
      label: `${matrix.ungovernedAgentCount} ungoverned agent${
        matrix.ungovernedAgentCount === 1 ? "" : "s"
      }`,
      gap: matrix.ungovernedAgentCount > 0,
    },
    { label: `${matrix.customCount} custom`, gap: matrix.customCount > 0 },
  ];

  return (
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 rounded-md border border-border bg-muted/30 px-3 py-2 text-sm">
      {stats.map((stat, index) => (
        <span key={stat.label} className="flex items-center gap-3">
          {index > 0 && <span className="text-muted-foreground">·</span>}
          <span
            className={cn(
              stat.gap
                ? "text-amber-600 dark:text-amber-400"
                : "text-muted-foreground"
            )}
          >
            {stat.label}
          </span>
        </span>
      ))}
    </div>
  );
}

// --- main component -------------------------------------------------------

export default function PoliciesMatrix({
  matrix,
  agents,
  onEditRule,
  onAddRule,
}: {
  matrix: PolicyMatrix;
  agents: AgentOption[];
  onEditRule: (ruleId: string) => void;
  onAddRule: (scope: AddRuleScope) => void;
}) {
  const [query, setQuery] = useState("");
  const [show, setShow] = useState<ShowFilter>("all");
  const [drawerOpen, setDrawerOpen] = useState(false);
  const [active, setActive] = useState<MatrixSubject | null>(null);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return matrix.subjects.filter((subject) => {
      if (show === "gaps" && !hasGap(subject)) return false;
      if (q && !subject.subjectName.toLowerCase().includes(q)) return false;
      return true;
    });
  }, [matrix.subjects, query, show]);

  // Keep the open drawer in sync with refreshed matrix data after a save.
  const activeSubject = useMemo(() => {
    if (!active) return null;
    return (
      matrix.subjects.find((s) => s.subjectKey === active.subjectKey) ?? active
    );
  }, [active, matrix.subjects]);

  const handleOpen = (subject: MatrixSubject) => {
    setActive(subject);
    setDrawerOpen(true);
  };

  const handleEditRule = (ruleId: string) => {
    setDrawerOpen(false);
    onEditRule(ruleId);
  };

  const handleAddRule = (scope: AddRuleScope) => {
    setDrawerOpen(false);
    onAddRule(scope);
  };

  return (
    <TooltipProvider delayDuration={200}>
      <div className="space-y-3">
        <RiskStrip matrix={matrix} />

        <div className="flex flex-wrap items-center gap-2">
          <div className="relative min-w-[180px] flex-1">
            <Search className="pointer-events-none absolute left-3 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-muted-foreground" />
            <Input
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Search subjects…"
              className="h-9 pl-9"
            />
          </div>
          <Select value={show} onValueChange={(v) => setShow(v as ShowFilter)}>
            <SelectTrigger className="h-9 w-auto min-w-[130px]">
              <SelectValue placeholder="Show" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">Show: All</SelectItem>
              <SelectItem value="gaps">Show: With gaps</SelectItem>
            </SelectContent>
          </Select>
        </div>

        <div className="overflow-hidden rounded-lg border border-border">
          <TableComponent>
            <TableHeader>
              <TableRow className="pointer-events-none hover:bg-transparent">
                <TableHead className="h-auto py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground first:pl-5">
                  Subject
                </TableHead>
                <TableHead className="h-auto py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Budget
                </TableHead>
                <TableHead className="h-auto py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Tokens
                </TableHead>
                <TableHead className="h-auto py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Tools
                </TableHead>
                <TableHead className="h-auto py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Approval
                </TableHead>
                <TableHead className="h-auto py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Safety
                </TableHead>
                <TableHead className="h-auto py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Custom
                </TableHead>
                <TableHead className="h-auto py-2 text-[11px] font-medium uppercase tracking-wide text-muted-foreground last:pr-5">
                  Status
                </TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {filtered.length === 0 ? (
                <TableRow className="hover:bg-transparent">
                  <TableCell
                    colSpan={COLUMN_COUNT}
                    className="py-8 text-center text-sm text-muted-foreground"
                  >
                    No subjects match the current filters.
                  </TableCell>
                </TableRow>
              ) : (
                filtered.map((subject) => (
                  <MatrixRow
                    key={subject.subjectKey}
                    subject={subject}
                    agents={agents}
                    onOpen={handleOpen}
                  />
                ))
              )}
            </TableBody>
          </TableComponent>
        </div>
      </div>

      <DetailDrawer
        subject={activeSubject}
        open={drawerOpen}
        onOpenChange={setDrawerOpen}
        onEditRule={handleEditRule}
        onAddRule={handleAddRule}
      />
    </TooltipProvider>
  );
}
