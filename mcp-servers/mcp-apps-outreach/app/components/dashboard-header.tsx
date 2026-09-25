import { PERIODS, type Period } from "@shared/outreach";
import type { Snapshot } from "@shared/schema";
import { Radar, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectSeparator, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { formatDateTime } from "@/lib/format";
import { cn } from "@/lib/utils";

/** "Updated 2m ago" against the viewer's clock, ticking while the dashboard is open. */
function useUpdatedLabel(generatedAt: string | undefined) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 30_000);
    return () => window.clearInterval(timer);
  }, []);
  if (!generatedAt) return "Loading…";
  const minutes = Math.floor((now - Date.parse(generatedAt)) / 60_000);
  if (minutes < 1) return "Updated just now";
  if (minutes < 60) return `Updated ${minutes}m ago`;
  return `Updated ${Math.floor(minutes / 60)}h ago`;
}

export function DashboardHeader({
  snapshot,
  campaign,
  onCampaignChange,
  days,
  onDaysChange,
  loading,
  onRefresh,
}: {
  snapshot: Snapshot | null;
  campaign: string;
  onCampaignChange: (campaign: string) => void;
  days: Period;
  onDaysChange: (days: Period) => void;
  loading: boolean;
  onRefresh: () => void;
}) {
  const updated = useUpdatedLabel(snapshot?.generatedAt);

  return (
    <header className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
      <div className="flex min-w-0 items-center gap-3">
        <div className="bg-primary text-primary-foreground flex size-9 shrink-0 items-center justify-center rounded-lg shadow-xs">
          <Radar className="size-[18px]" strokeWidth={2.25} />
        </div>
        <div className="min-w-0">
          <h1 className="truncate text-[15px] leading-tight font-semibold tracking-tight">Outbound signals</h1>
          <p className="text-muted-foreground truncate text-xs">
            {snapshot ? (
              <>
                {snapshot.sender.company} · data as of {formatDateTime(snapshot.asOf)}
              </>
            ) : (
              "Connecting to the outreach server…"
            )}
          </p>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Select value={campaign} onValueChange={onCampaignChange}>
          <SelectTrigger size="sm" className="min-w-[210px]" aria-label="Campaign">
            <SelectValue />
          </SelectTrigger>
          <SelectContent align="end">
            <SelectItem value="all">All campaigns</SelectItem>
            <SelectSeparator />
            {(snapshot?.campaigns ?? []).map((c) => (
              <SelectItem key={c.id} value={c.id}>
                {c.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>

        <Tabs value={String(days)} onValueChange={(value) => onDaysChange(Number(value) as Period)}>
          <TabsList aria-label="Period">
            {PERIODS.map((period) => (
              <TabsTrigger key={period} value={String(period)} className="tabular min-w-11">
                {period}d
              </TabsTrigger>
            ))}
          </TabsList>
        </Tabs>

        <Tooltip>
          <TooltipTrigger asChild>
            <Button variant="outline" size="sm" onClick={onRefresh} disabled={loading} className="text-muted-foreground">
              <RefreshCw className={cn(loading && "animate-spin")} />
              <span className="tabular hidden text-xs sm:inline">{loading ? "Refreshing…" : updated}</span>
            </Button>
          </TooltipTrigger>
          <TooltipContent>Refresh from the MCP server</TooltipContent>
        </Tooltip>
      </div>
    </header>
  );
}
