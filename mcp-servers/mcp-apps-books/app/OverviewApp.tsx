import type { Period } from "@shared/period";
import type { Overview } from "@shared/schema";
import { ErrorBanner } from "@kit/components/notes";
import { StatSkeleton } from "@kit/components/skeletons";
import { FilterRow, Page, RefreshButton, ViewHeader } from "@kit/components/view-header";
import { Skeleton } from "@kit/ui/skeleton";
import { BookOpen } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { AccountsCard } from "@/components/overview/accounts-card";
import { KpiCards } from "@/components/overview/kpi-cards";
import { MonthlyChart } from "@/components/overview/monthly-chart";
import { PnlCard } from "@/components/overview/pnl-card";
import { ReceivablesCard } from "@/components/overview/receivables-card";
import { ReviewBanner } from "@/components/overview/review-banner";
import { PeriodSwitcher } from "@/components/period-switcher";
import { StandaloneNotice } from "@kit/components/standalone-notice";
import { TooltipProvider } from "@kit/ui/tooltip";
import { dayMonth } from "@/lib/format";
import { call, messageOf, openAppView, useView } from "@kit/lib/mcp";

export function OverviewApp() {
  // Opened directly rather than inside an MCP host: there is no bridge and no data.
  if (window.parent === window) return <StandaloneNotice title="Books overview" icon={BookOpen} server="books" />;
  return <ConnectedOverview />;
}

const periodArgs = (p: Period | null) =>
  !p ? {} : p.kind === "custom" ? { period: p.kind, from: p.from, to: p.to } : { period: p.kind, date: p.from };

function ConnectedOverview() {
  const { app, isConnected, payload: overview, setPayload, error, setError } = useView<Overview>("Books overview");
  const [loading, setLoading] = useState(false);
  const request = useRef(0);

  const load = useCallback(
    async (period: Period | null) => {
      if (!app) return;
      const id = ++request.current;
      setLoading(true);
      try {
        const next = await call<Overview>(app, "show_books_overview", periodArgs(period));
        if (id !== request.current) return;
        setPayload(next);
        setError(null);
      } catch (failure) {
        if (id === request.current) setError(messageOf(failure));
      } finally {
        if (id === request.current) setLoading(false);
      }
    },
    [app, setPayload, setError],
  );

  // Without the host's own result (some hosts send none to a re-opened view), fetch this month.
  useEffect(() => {
    if (!isConnected || overview) return;
    const timer = window.setTimeout(() => {
      if (request.current === 0) void load(null);
    }, 1500);
    return () => window.clearTimeout(timer);
  }, [isConnected, overview, load]);

  const open = (tool: string, args: Record<string, string>) =>
    app ? openAppView(app, tool, args) : Promise.resolve("Not connected to a host");
  const range: Record<string, string> = overview ? { from: overview.period.from, to: overview.period.to } : {};

  return (
    <TooltipProvider>
      <Page>
        <header className="flex flex-col gap-3">
          <ViewHeader
            icon={BookOpen}
            title={overview?.book.name ?? "Books"}
            subtitle={
              overview
                ? `${overview.book.legalName} · ${overview.book.baseCurrency} · today ${dayMonth(overview.today)} ${overview.today.slice(0, 4)}`
                : "Connecting to the books server…"
            }
            actions={
              <RefreshButton
                busy={loading || !overview}
                onClick={() => overview && void load(overview.period)}
                label="Reload from the books server"
              />
            }
          />
          {overview && (
            <FilterRow>
              <PeriodSwitcher
                period={overview.period}
                today={overview.today}
                onChange={(p) => void load(p)}
                disabled={loading}
              />
            </FilterRow>
          )}
        </header>

        <ErrorBanner message={error} />

        {overview ? (
          <div
            className="flex flex-col gap-5 transition-opacity duration-200 data-[loading=true]:opacity-60"
            data-loading={loading}
            aria-busy={loading}
          >
            <ReviewBanner overview={overview} onReview={() => open("show_transactions", { uncategorized: "true" })} />
            <KpiCards overview={overview} />
            <div className="grid gap-5 lg:grid-cols-12 [&>*]:min-w-0">
              <MonthlyChart className="lg:col-span-8" overview={overview} />
              <AccountsCard
                className="lg:col-span-4"
                overview={overview}
                onOpenAccount={(account) => open("show_transactions", { account, ...range })}
              />
            </div>
            <div className="grid gap-5 lg:grid-cols-12 [&>*]:min-w-0">
              <PnlCard
                className="lg:col-span-7"
                overview={overview}
                onOpenCategory={(category) =>
                  open("show_transactions", category ? { category, ...range } : { uncategorized: "true", ...range })
                }
              />
              <ReceivablesCard
                className="lg:col-span-5"
                overview={overview}
                onOpenInvoice={(number) => open("show_invoice", { number })}
              />
            </div>
          </div>
        ) : (
          !error && (
            <div className="flex flex-col gap-5" aria-busy="true" aria-label="Loading the books">
              <StatSkeleton count={6} className="md:grid-cols-3 lg:grid-cols-3 xl:grid-cols-6" />
              <div className="grid gap-5 lg:grid-cols-12">
                <Skeleton className="h-[280px] rounded-lg lg:col-span-8" />
                <Skeleton className="h-[280px] rounded-lg lg:col-span-4" />
              </div>
            </div>
          )
        )}
      </Page>
    </TooltipProvider>
  );
}
