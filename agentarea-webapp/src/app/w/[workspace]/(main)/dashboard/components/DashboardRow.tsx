import type { ReactNode } from "react";
import { AgentAvatar } from "@/components/AgentAvatar";
import { CollapsibleGroup } from "@/components/ui/group-header";
import { InteractiveListRow } from "@/components/ui/interactive-list-row";
import { StatusIndicator } from "@/components/ui/status-indicator";
import Link from "@/components/WorkspaceLink";
import type { StatusKind } from "@/lib/status";

export type RowAgentRef = { id: string; name: string };

/**
 * A dashboard list row on one line, laid out in fixed columns so rows line up:
 * status glyph, title with its detail, agent, time, and — when the list has
 * one — an amount. A missing value keeps its column empty.
 */
export function DashboardRow({
  href,
  status,
  title,
  count,
  detail,
  agent,
  time,
  amount,
}: {
  href: string;
  status: ReactNode;
  title: string;
  /** How many runs the row stands for, when it folds several. */
  count?: number;
  detail?: string | null;
  agent?: RowAgentRef | null;
  time?: string | null;
  /** Leave undefined in a list without amounts; null is an empty cell. */
  amount?: string | null;
}) {
  return (
    <Link href={href} className="block">
      <InteractiveListRow
        className="px-6 py-1.5"
        start={<span className="flex">{status}</span>}
      >
        <div className="flex w-full min-w-0 items-center gap-3 text-[12px] text-muted-foreground">
          <span className="flex min-w-0 flex-1 items-center gap-2">
            <span className="max-w-[45%] shrink-0 truncate text-[13px] font-medium text-foreground">
              {title}
            </span>
            {count != null && count > 1 && (
              <span className="shrink-0 rounded-full bg-muted px-[7px] text-[11.5px] leading-[17px] tabular-nums">
                ×{count}
              </span>
            )}
            {detail && (
              <span className="min-w-0 flex-1 truncate">{detail}</span>
            )}
          </span>
          <span className="flex w-[120px] shrink-0 items-center gap-2">
            {agent && (
              <>
                <AgentAvatar agent={agent} size="xs" />
                <span className="truncate font-medium">{agent.name}</span>
              </>
            )}
          </span>
          <span className="w-[72px] shrink-0 truncate text-right font-mono">
            {time}
          </span>
          {amount !== undefined && (
            <span className="w-[64px] shrink-0 truncate text-right font-mono">
              {amount}
            </span>
          )}
        </div>
      </InteractiveListRow>
    </Link>
  );
}

export type Row = {
  key: string;
  href: string;
  status: ReactNode;
  title: string;
  count?: number;
  detail?: string | null;
  agent?: RowAgentRef | null;
  time?: string | null;
  amount?: string | null;
};

/**
 * A collapsible group of dashboard rows; nothing when it has none. The header
 * counts runs, so a folded row counts as many.
 */
export function RowGroup({
  label,
  kind,
  rows,
}: {
  label: string;
  kind: StatusKind;
  rows: Row[];
}) {
  if (rows.length === 0) return null;
  return (
    <CollapsibleGroup
      label={label}
      count={rows.reduce((n, r) => n + (r.count ?? 1), 0)}
      icon={<StatusIndicator kind={kind} size="sm" aria-label={label} />}
      sticky={false}
      headerClassName="px-6 lg:sticky lg:top-0 lg:z-10"
    >
      {rows.map(({ key, ...row }) => (
        <DashboardRow key={key} {...row} />
      ))}
    </CollapsibleGroup>
  );
}
