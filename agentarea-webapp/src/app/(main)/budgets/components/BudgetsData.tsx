import { SpendCard } from "@/app/(main)/dashboard/components/SpendCard";
import EmptyState from "@/components/EmptyState";
import { getDashboard, getWorkspaceSettings } from "@/lib/api-dashboard";
import { BudgetCapPanel } from "./BudgetCapPanel";

const fmt = (v: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
    maximumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
  }).format(v);

export async function BudgetsData() {
  let data: Awaited<ReturnType<typeof getDashboard>> | null = null;
  let settings: Awaited<ReturnType<typeof getWorkspaceSettings>> | null = null;
  let error: string | null = null;
  let settingsError: string | null = null;

  try {
    const [dashboardResult, settingsResult] = await Promise.allSettled([
      getDashboard(),
      getWorkspaceSettings(),
    ]);

    if (dashboardResult.status === "fulfilled") {
      data = dashboardResult.value;
    } else {
      throw dashboardResult.reason;
    }

    if (settingsResult.status === "fulfilled") {
      settings = settingsResult.value;
    } else {
      settingsError =
        settingsResult.reason instanceof Error
          ? settingsResult.reason.message
          : "Failed to load workspace settings";
    }
  } catch (e) {
    console.error("Failed to load budgets data:", e);
    error = e instanceof Error ? e.message : "Failed to load budget data";
  }

  if (error) {
    return (
      <EmptyState
        title="Couldn't load budget data"
        description={error}
        iconsType="payments"
      />
    );
  }

  if (!data) return null;

  const cap = settings?.monthly_cap_usd ?? data.spend.cap_usd;
  const projected = data.spend.projected_eom_usd;

  return (
    <div className="mx-auto w-full max-w-[980px] space-y-6">
      <div className="grid gap-x-10 gap-y-6 lg:grid-cols-5 lg:divide-x lg:divide-border/50">
        <div className="lg:col-span-3 lg:pr-10">
          <SpendCard spend={data.spend} trend={data.daily_spend} />
        </div>

        <section className="lg:col-span-2 lg:pl-10">
          <header className="flex items-baseline justify-between">
            <h3 className="text-[13px] font-medium text-foreground">
              Month outlook
            </h3>
            <span className="text-[11px] text-muted-foreground tabular-nums">
              Current period
            </span>
          </header>

          <dl className="mt-4 space-y-3">
            <div className="flex items-baseline justify-between gap-4 border-b border-border/50 pb-3">
              <dt className="text-[12px] text-muted-foreground">Today</dt>
              <dd className="text-sm font-medium tabular-nums">
                {fmt(data.spend.today_usd)}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4 border-b border-border/50 pb-3">
              <dt className="text-[12px] text-muted-foreground">
                Projected end of month
              </dt>
              <dd className="text-sm font-medium tabular-nums">
                {projected == null ? "No projection" : fmt(projected)}
              </dd>
            </div>
            <div className="flex items-baseline justify-between gap-4">
              <dt className="text-[12px] text-muted-foreground">Monthly cap</dt>
              <dd className="text-sm font-medium tabular-nums">
                {cap == null ? "Not set" : fmt(cap)}
              </dd>
            </div>
          </dl>
        </section>
      </div>

      <div className="border-t border-border/50 pt-6">
        <BudgetCapPanel
          initialCap={cap}
          mtdSpend={data.spend.mtd_usd}
          settingsError={settingsError}
        />
      </div>
    </div>
  );
}
