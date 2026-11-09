import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { Shield } from "lucide-react";
import type {
  Blockers,
  BrokenConnection,
  BrokenTrigger,
  Health,
} from "@/api/client";
import { BoardSectionHeader } from "@/components/board";
import { StatusIndicator } from "@/components/ui/status-indicator";
import {
  getBrokenConnectionStatusPresentation,
  getBrokenTriggerStatusPresentation,
  type StatusKind,
} from "@/lib/status";
import { RowGroup, type Row } from "./DashboardRow";
import { formatRelTime } from "./relTime";
import { firstLine, groupStopped } from "./stopped";

/** What waits on a person, what stopped, and what is broken; an all-clear when nothing is. */
export function AttentionPanel({
  blockers,
  health,
}: {
  blockers: Blockers;
  health: Health;
}) {
  const t = useTranslations("DashboardPage");
  const ago = (iso: string | null) => formatRelTime(iso, t);
  const glyph = (kind: StatusKind, label: string) => (
    <StatusIndicator kind={kind} size="sm" aria-label={label} />
  );

  const taskRow = (
    b: { task_id: string; agent_id: string; agent_name?: string | null },
    kind: StatusKind,
    label: string,
    title: string,
    at: string | null
  ): Row => ({
    key: `${label}-${b.task_id}`,
    href: `/tasks/${b.task_id}`,
    status: glyph(kind, label),
    title,
    detail: label,
    agent: b.agent_name ? { id: b.agent_id, name: b.agent_name } : null,
    time: ago(at),
  });

  const decision: Row[] = [
    ...blockers.hitl.map((b) =>
      taskRow(
        b,
        "attention",
        t("waitingFor", { status: b.status }),
        b.description,
        b.created_at
      )
    ),
    ...blockers.awaiting_continuation.map((b) =>
      taskRow(
        b,
        "attention",
        t("waitingFor", { status: "waiting_for_continuation" }),
        b.description,
        b.created_at
      )
    ),
  ];

  const stopped: Row[] = groupStopped(
    blockers.blocked_24h,
    blockers.failed_24h
  ).map((g) => {
    const blocked = g.kind === "blocked";
    return {
      ...taskRow(
        g.latest,
        blocked ? "attention" : "failed",
        blocked ? t("blocked") : t("failed"),
        g.reason || (blocked ? t("taskBlocked") : t("taskFailed")),
        g.latest.occurred_at
      ),
      key: g.key,
      count: g.count,
    };
  });

  const connectionRow = (c: BrokenConnection): Row => {
    const label = t(`connectionReason.${c.reason}`);
    const error = firstLine(c.error);
    return {
      key: `connection-${c.instance_id}`,
      href: `/connections/${c.instance_id}`,
      status: glyph(
        getBrokenConnectionStatusPresentation(c.reason).kind,
        label
      ),
      title: c.name,
      detail: error ? `${label} · ${error}` : label,
      time: c.at ? ago(c.at) : null,
    };
  };

  const triggerRow = (tr: BrokenTrigger): Row => {
    const label = t(`triggerReason.${tr.reason}`, {
      count: tr.consecutive_failures,
      threshold: tr.failure_threshold,
    });
    return {
      key: `trigger-${tr.trigger_id}`,
      href: `/triggers/${tr.trigger_id}`,
      status: glyph(getBrokenTriggerStatusPresentation(tr.reason).kind, label),
      title: tr.name,
      detail: label,
      agent: tr.agent_name ? { id: tr.agent_id, name: tr.agent_name } : null,
      time: tr.last_execution_at ? ago(tr.last_execution_at) : null,
    };
  };

  const broken: Row[] = [
    ...health.connections.map(connectionRow),
    ...health.triggers.map(triggerRow),
  ];

  const total = [...decision, ...stopped, ...broken].reduce(
    (n, r) => n + (r.count ?? 1),
    0
  );

  let body: ReactNode;
  if (total === 0) {
    body = (
      <div className="flex h-full items-center gap-3 px-6 py-6">
        <StatusIndicator
          kind="done"
          iconClassName="h-5 w-5"
          className="mt-px"
          aria-label={t("allClearTitle")}
        />
        <div className="min-w-0">
          <div className="text-[14px] font-medium text-foreground">
            {t("allClearTitle")}
          </div>
          <div className="mt-1 text-[12.5px] text-muted-foreground">
            {t("allClearHint")}
          </div>
        </div>
      </div>
    );
  } else {
    body = (
      <>
        <RowGroup
          label={t("waitingForDecision")}
          kind="attention"
          rows={decision}
        />
        <RowGroup label={t("stopped")} kind="failed" rows={stopped} />
        <RowGroup label={t("broken")} kind="failed" rows={broken} />
      </>
    );
  }

  return (
    <div className="flex min-h-0 flex-col">
      <div className="border-b border-zinc-200 px-6 pb-3 pt-4 dark:border-zinc-700">
        <BoardSectionHeader
          icon={<Shield />}
          color="hsl(var(--foreground))"
          title={t("attention")}
          pill={total}
        />
      </div>
      <div className="lg:h-[264px] lg:overflow-y-auto">{body}</div>
    </div>
  );
}
