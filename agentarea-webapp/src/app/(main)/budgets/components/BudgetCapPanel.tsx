"use client";

import { useMemo, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { AlertTriangle, CheckCircle2, DollarSign, Gauge } from "lucide-react";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import FormLabel from "@/components/FormLabel/FormLabel";
import { updateWorkspaceSettingsAction } from "@/lib/server-actions";
import { cn } from "@/lib/utils";

const fmt = (v: number) =>
  new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
    maximumFractionDigits: v > 0 && v < 0.01 ? 4 : 2,
  }).format(v);

function parseCap(value: string, invalidMsg: string) {
  const trimmed = value.trim();
  if (!trimmed) return { value: null, error: null };

  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return { value: null, error: invalidMsg };
  }

  return { value: parsed, error: null };
}

function barTone(pct: number) {
  if (pct >= 100) return "bg-[color:var(--status-danger)]";
  if (pct >= 80) return "bg-[color:var(--status-warning)]";
  return "bg-[color:var(--violet)]";
}

function pctTone(pct: number) {
  if (pct >= 100) return "text-red-600 dark:text-red-400";
  if (pct >= 80) return "text-amber-600 dark:text-amber-400";
  return "text-muted-foreground";
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
  const t = useTranslations("BudgetsPage");
  const router = useRouter();
  const [cap, setCap] = useState(initialCap);
  const [capInput, setCapInput] = useState(
    initialCap == null ? "" : String(initialCap)
  );
  const [status, setStatus] = useState<"idle" | "success" | "error">("idle");
  const [message, setMessage] = useState<string | null>(settingsError);
  const [isPending, startTransition] = useTransition();

  const parsed = useMemo(
    () => parseCap(capInput, t("capInvalid")),
    [capInput, t]
  );
  const hasChanges = parsed.error == null && parsed.value !== cap;
  const canSave = hasChanges && !isPending;
  const capPct = cap && cap > 0 ? (mtdSpend / cap) * 100 : null;
  const displayPct = capPct == null ? 0 : Math.min(capPct, 100);

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
        setMessage(error || t("capUpdateFailed"));
        return;
      }

      setCap(data.monthly_cap_usd);
      setCapInput(
        data.monthly_cap_usd == null ? "" : String(data.monthly_cap_usd)
      );
      setStatus("success");
      setMessage(t("capUpdated"));
      router.refresh();
    });
  };

  return (
    <section className="grid items-start gap-x-8 gap-y-6 px-0 py-1 lg:p-5 lg:grid-cols-[minmax(0,1fr)_300px]">
      {/* lead — icon + title + description */}
      <div className="flex gap-3.5 lg:col-start-1">
        <EntityAvatar
          variant="soft"
          size={38}
          color="var(--violet)"
          icon={<Gauge />}
          lines={false}
        />
        <div>
          <h3 className="text-[14.5px] font-semibold tracking-[-0.01em] text-foreground">
            {t("capTitle")}
          </h3>
          <p className="mt-1 max-w-[46ch] text-[12.5px] text-muted-foreground">
            {t("capDesc")}
          </p>
        </div>
      </div>

      {/* form — right column, spans both rows on desktop */}
      <div className="flex flex-col gap-2.5 lg:col-start-2 lg:row-span-2 lg:row-start-1">
        <FormLabel
          htmlFor="monthly-cap"
          icon={DollarSign}
          className="text-[12px] font-semibold text-foreground/80"
        >
          {t("capField")}
        </FormLabel>
        <div className="flex flex-col gap-2.5 sm:flex-row">
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
            placeholder={t("capPlaceholder")}
            disabled={isPending}
            className="h-[38px] flex-1 font-mono tabular-nums"
          />
          <Button
            type="button"
            className="h-[38px] sm:self-start"
            isLoading={isPending}
            disabled={!canSave}
            onClick={saveCap}
          >
            {t("save")}
          </Button>
        </div>

        <p
          className={cn(
            "flex items-start gap-1.5 text-[11.5px]",
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
          <span>{message ?? t("capNote")}</span>
        </p>
      </div>

      {/* usage — left column, second row */}
      <div className="lg:col-start-1 lg:row-start-2">
        {cap == null ? (
          <p className="text-[13px] text-muted-foreground">{t("capNoCap")}</p>
        ) : (
          <>
            <div className="flex items-baseline justify-between text-[12px]">
              <span className="font-medium tabular-nums text-foreground">
                {t("capUsed", { amount: fmt(mtdSpend) })}
              </span>
              <span
                className={cn(
                  "font-medium tabular-nums",
                  pctTone(capPct ?? 0)
                )}
              >
                {t("capOfTotal", {
                  pct: (capPct ?? 0).toFixed(1),
                  cap: fmt(cap),
                })}
              </span>
            </div>
            <div className="mt-2.5 h-[7px] overflow-hidden rounded-full bg-zinc-100 dark:bg-zinc-700/80">
              <div
                className={cn("h-full rounded-full", barTone(capPct ?? 0))}
                style={{ width: `${displayPct}%` }}
              />
            </div>
          </>
        )}
      </div>
    </section>
  );
}
