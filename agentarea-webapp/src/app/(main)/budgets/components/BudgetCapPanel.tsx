"use client";

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle, CheckCircle2, DollarSign, Gauge } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Progress } from "@/components/ui/progress";
import { updateWorkspaceSettingsAction } from "@/lib/server-actions";
import { cn } from "@/lib/utils";

const fmt = (v: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
    maximumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
  }).format(v);

function parseCap(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return { value: null, error: null };

  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return {
      value: null,
      error: "Enter a positive number, or leave it empty to remove the cap.",
    };
  }

  return { value: parsed, error: null };
}

export function BudgetCapPanel({
  initialCap,
  mtdSpend,
  settingsError,
}: {
  initialCap: number | null;
  mtdSpend: number;
  settingsError: string | null;
}) {
  const router = useRouter();
  const [cap, setCap] = useState(initialCap);
  const [capInput, setCapInput] = useState(
    initialCap == null ? "" : String(initialCap)
  );
  const [status, setStatus] = useState<"idle" | "success" | "error">("idle");
  const [message, setMessage] = useState<string | null>(settingsError);
  const [isPending, startTransition] = useTransition();

  const parsed = useMemo(() => parseCap(capInput), [capInput]);
  const capPct = cap && cap > 0 ? (mtdSpend / cap) * 100 : null;
  const displayPct = capPct == null ? 0 : Math.min(capPct, 100);
  const isOverCap = capPct != null && capPct >= 100;
  const isNearCap = capPct != null && capPct >= 80 && capPct < 100;

  const saveCap = () => {
    if (parsed.error) {
      setStatus("error");
      setMessage(parsed.error);
      return;
    }

    setStatus("idle");
    setMessage(null);

    startTransition(async () => {
      const { data, error } = await updateWorkspaceSettingsAction(parsed.value);
      if (error || !data) {
        setStatus("error");
        setMessage(error || "Failed to update workspace cap");
        return;
      }

      setCap(data.monthly_cap_usd);
      setCapInput(
        data.monthly_cap_usd == null ? "" : String(data.monthly_cap_usd)
      );
      setStatus("success");
      setMessage("Workspace monthly cap updated.");
      router.refresh();
    });
  };

  return (
    <section className="rounded-md border border-zinc-200/70 bg-white p-4 dark:border-zinc-800 dark:bg-zinc-900">
      <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="grid h-8 w-8 shrink-0 place-items-center rounded-md border border-border bg-muted/30">
              <Gauge className="h-4 w-4 text-primary dark:text-accent-foreground" />
            </span>
            <div>
              <h3 className="text-[13px] font-medium text-foreground">
                Workspace monthly cap
              </h3>
              <p className="mt-0.5 text-xs text-muted-foreground">
                New tasks are refused once month-to-date spend reaches this
                amount.
              </p>
            </div>
          </div>

          <div className="mt-4 max-w-xl">
            {cap == null ? (
              <p className="text-sm text-muted-foreground">
                No cap is set. Workspace spend can continue without a monthly
                stop.
              </p>
            ) : (
              <>
                <div className="flex items-baseline justify-between gap-3 text-sm">
                  <span className="text-muted-foreground">
                    {fmt(mtdSpend)} used
                  </span>
                  <span
                    className={cn(
                      "font-medium tabular-nums",
                      isOverCap
                        ? "text-red-600 dark:text-red-400"
                        : isNearCap
                          ? "text-amber-600 dark:text-amber-400"
                          : "text-muted-foreground"
                    )}
                  >
                    {capPct?.toFixed(1)}% of {fmt(cap)}
                  </span>
                </div>
                <Progress
                  value={displayPct}
                  className={cn(
                    "mt-2 h-[3px]",
                    isOverCap
                      ? "[&>div]:bg-red-500"
                      : isNearCap
                        ? "[&>div]:bg-amber-500"
                        : "[&>div]:bg-foreground/70"
                  )}
                />
              </>
            )}
          </div>
        </div>

        <div className="w-full shrink-0 md:w-[280px]">
          <label
            htmlFor="monthly-cap"
            className="mb-2 flex items-center gap-1.5 text-xs font-medium text-foreground"
          >
            <DollarSign className="h-4 w-4 text-primary dark:text-accent-foreground" />
            Monthly cap (USD)
          </label>
          <div className="flex gap-2">
            <Input
              id="monthly-cap"
              type="number"
              min="0"
              step="0.01"
              value={capInput}
              onChange={(event) => {
                setCapInput(event.target.value);
                setStatus("idle");
                setMessage(settingsError);
              }}
              placeholder="No cap"
              disabled={isPending}
              className="h-8"
            />
            <Button
              type="button"
              size="sm"
              isLoading={isPending}
              disabled={isPending}
              onClick={saveCap}
            >
              Save
            </Button>
          </div>

          {message && (
            <div
              className={cn(
                "mt-3 flex items-start gap-2 text-xs",
                status === "success"
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-muted-foreground",
                status === "error" && "text-destructive"
              )}
            >
              {status === "success" ? (
                <CheckCircle2 className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              ) : status === "error" ? (
                <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
              ) : null}
              <span>{message}</span>
            </div>
          )}
        </div>
      </div>
    </section>
  );
}
