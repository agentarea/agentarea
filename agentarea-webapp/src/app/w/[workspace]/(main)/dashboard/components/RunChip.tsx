import type { ScheduledRun } from "@/api/client";
import { AgentAvatar } from "@/components/AgentAvatar";
import Link from "@/components/WorkspaceLink";

/** A run is either a cron trigger firing or a task booked for later. */
export function runHref(run: ScheduledRun) {
  return run.task_id ? `/tasks/${run.task_id}` : `/triggers/${run.trigger_id}`;
}

export function runKey(run: ScheduledRun) {
  return `${run.task_id ?? run.trigger_id}-${run.fires_at}`;
}

export function runName(run: ScheduledRun) {
  return run.agent_name ? `${run.title} · ${run.agent_name}` : run.title;
}

export function RunChip({
  run,
  time,
  date,
  withAgent = false,
}: {
  run: ScheduledRun;
  time: (iso: string) => string;
  /** The run's full date: the chip alone shows only the time. */
  date: string;
  /** The grid cell is too narrow for the avatar; the tooltip names the agent. */
  withAgent?: boolean;
}) {
  const name = runName(run);
  return (
    <Link
      href={runHref(run)}
      className="flex min-w-0 items-center gap-1.5 rounded-md border border-zinc-200 bg-background px-1.5 py-0.5 text-[11.5px] leading-[18px] transition-colors hover:bg-muted dark:border-zinc-700"
      title={name}
      aria-label={`${date} ${time(run.fires_at)} ${name}`}
    >
      {withAgent && (
        <AgentAvatar
          agent={{ id: run.agent_id, name: run.agent_name ?? "" }}
          size="xs"
        />
      )}
      <span className="shrink-0 font-mono text-[10.5px] text-muted-foreground">
        {time(run.fires_at)}
      </span>
      <span className="min-w-0 truncate font-medium text-foreground">
        {run.title}
      </span>
    </Link>
  );
}
