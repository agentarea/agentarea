import Link from "next/link";
import type { DashboardData } from "@/lib/api-dashboard";

const SECTION_TONE: Record<
  "hitl" | "wallet" | "failed",
  { dot: string; label: string }
> = {
  hitl: { dot: "bg-amber-500", label: "Awaiting input" },
  wallet: { dot: "bg-blue-500", label: "Wallet exhausted" },
  failed: { dot: "bg-red-500", label: "Failed (24h)" },
};

export function BlockersPanel({
  blockers,
}: {
  blockers: DashboardData["blockers"];
}) {
  const total =
    blockers.hitl.length +
    blockers.wallet_exhausted.length +
    blockers.failed_24h.length;

  return (
    <section>
      <header className="flex items-baseline justify-between">
        <h3 className="text-[13px] font-medium text-foreground">Blockers</h3>
        <span className="text-[11px] text-muted-foreground tabular-nums">
          {total === 0 ? "Healthy" : total}
        </span>
      </header>

      <div className="mt-3 space-y-4">
        {total === 0 && (
          <div className="py-6 text-center text-[11px] text-muted-foreground">
            Nothing blocking work right now.
          </div>
        )}

        {blockers.hitl.length > 0 && (
          <Section kind="hitl" count={blockers.hitl.length}>
            {blockers.hitl.slice(0, 5).map((b) => (
              <Link
                key={b.task_id}
                href={`/tasks/${b.task_id}`}
                className="-mx-2 block rounded px-2 py-1.5 transition-colors hover:bg-muted/50"
              >
                <div className="truncate text-[12px]">{b.description}</div>
                <div className="truncate text-[11px] text-muted-foreground">
                  {b.agent_name}
                </div>
              </Link>
            ))}
          </Section>
        )}

        {blockers.wallet_exhausted.length > 0 && (
          <Section kind="wallet" count={blockers.wallet_exhausted.length}>
            {blockers.wallet_exhausted.slice(0, 5).map((b) => (
              <Link
                key={b.agent_id}
                href={`/agents/${b.agent_id}`}
                className="-mx-2 flex items-center justify-between gap-2 rounded px-2 py-1.5 transition-colors hover:bg-muted/50"
              >
                <span className="truncate text-[12px]">{b.agent_name}</span>
                <span className="text-[11px] tabular-nums text-muted-foreground">
                  ${b.budget_usd.toFixed(2)} / {b.period}
                </span>
              </Link>
            ))}
          </Section>
        )}

        {blockers.failed_24h.length > 0 && (
          <Section kind="failed" count={blockers.failed_24h.length}>
            {blockers.failed_24h.slice(0, 5).map((b) => (
              <Link
                key={b.task_id}
                href={`/tasks/${b.task_id}`}
                className="-mx-2 block rounded px-2 py-1.5 transition-colors hover:bg-muted/50"
              >
                <div className="truncate text-[12px]">
                  {b.error?.split("\n")[0] || "Failed"}
                </div>
                <div className="truncate text-[11px] text-muted-foreground">
                  {b.agent_name}
                </div>
              </Link>
            ))}
          </Section>
        )}
      </div>
    </section>
  );
}

function Section({
  kind,
  count,
  children,
}: {
  kind: "hitl" | "wallet" | "failed";
  count: number;
  children: React.ReactNode;
}) {
  const tone = SECTION_TONE[kind];
  return (
    <div>
      <div className="mb-1 flex items-center gap-2">
        <span className={`h-1.5 w-1.5 rounded-full ${tone.dot}`} />
        <span className="text-[11px] font-medium text-foreground">
          {tone.label}
        </span>
        <span className="ml-auto text-[11px] tabular-nums text-muted-foreground">
          {count}
        </span>
      </div>
      <div className="space-y-0">{children}</div>
    </div>
  );
}
