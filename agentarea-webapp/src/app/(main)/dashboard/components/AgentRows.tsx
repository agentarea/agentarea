import Link from "next/link";
import { ChevronRight } from "lucide-react";
import { AgentAvatar } from "@/components/AgentAvatar";
import type { DashboardAgentRow } from "@/lib/api-dashboard";

const fmt = (v: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
    maximumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
  }).format(v);

const relTime = (iso: string | null) => {
  if (!iso) return "—";
  const d = new Date(iso);
  const diff = Date.now() - d.getTime();
  const mins = Math.round(diff / 60000);
  if (mins < 1) return "just now";
  if (mins < 60) return `${mins}m`;
  const hours = Math.round(mins / 60);
  if (hours < 24) return `${hours}h`;
  const days = Math.round(hours / 24);
  return `${days}d`;
};

function inferStatus(row: DashboardAgentRow): "idle" | "running" | "error" | null {
  if (!row.last_activity_at) return null;
  const lastMins =
    (Date.now() - new Date(row.last_activity_at).getTime()) / 60000;
  if (row.tasks_failed_today > 0 && lastMins < 60) return "error";
  if (lastMins < 5) return "running";
  return "idle";
}

export function AgentRows({ agents }: { agents: DashboardAgentRow[] }) {
  return (
    <section>
      <header className="flex items-baseline justify-between">
        <h3 className="text-[13px] font-medium text-foreground">Agents</h3>
        <span className="text-[11px] text-muted-foreground tabular-nums">
          {agents.length} active
        </span>
      </header>

      {agents.length === 0 ? (
        <div className="mt-4 py-6 text-center text-[12px] text-muted-foreground">
          No agents yet.{" "}
          <Link href="/agents" className="text-foreground underline-offset-2 hover:underline">
            Create your first agent
          </Link>
          .
        </div>
      ) : (
        <ul className="mt-2 -mx-2 divide-y divide-border/50">
          {agents.map((a) => {
            const failedToday = a.tasks_failed_today;
            return (
              <li key={a.agent_id}>
                <Link
                  href={`/agents/${a.agent_id}`}
                  className="group flex items-center gap-3 rounded px-2 py-2.5 transition-colors hover:bg-muted/50"
                >
                  <AgentAvatar
                    agent={{ id: a.agent_id, name: a.name }}
                    size="sm"
                    status={inferStatus(a)}
                  />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-2">
                      <span className="truncate text-[13px] font-medium">
                        {a.name}
                      </span>
                      <span className="text-[11px] text-muted-foreground tabular-nums">
                        {relTime(a.last_activity_at)}
                      </span>
                    </div>
                    <div className="truncate text-[11px] text-muted-foreground">
                      {a.recent_task_names[0] ?? "No recent activity"}
                    </div>
                  </div>
                  <div className="hidden shrink-0 gap-5 sm:flex">
                    <Stat label="Done" value={String(a.tasks_done_today)} />
                    <Stat
                      label="Failed"
                      value={String(failedToday)}
                      tone={
                        failedToday > 0
                          ? "text-red-600 dark:text-red-400"
                          : undefined
                      }
                    />
                    <Stat label="MTD" value={fmt(a.cost_mtd_usd)} />
                  </div>
                  <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/50 transition-colors group-hover:text-foreground" />
                </Link>
              </li>
            );
          })}
        </ul>
      )}
    </section>
  );
}

function Stat({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: string;
}) {
  return (
    <div className="text-right">
      <div className="text-[10px] text-muted-foreground">{label}</div>
      <div className={`text-[12px] font-medium tabular-nums ${tone ?? ""}`}>
        {value}
      </div>
    </div>
  );
}
