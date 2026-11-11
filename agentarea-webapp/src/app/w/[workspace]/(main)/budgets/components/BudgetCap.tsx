"use client";

import { useState, useTransition, type FormEvent } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Gauge, Pencil } from "lucide-react";
import { AdminOnlyHint } from "@/components/AdminOnlyState";
import { BoardSectionHeader } from "@/components/board";
import { CapMeter, capTone } from "@/components/CapMeter";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { StatusIndicator } from "@/components/ui/status-indicator";
import { useViewerCapabilities } from "@/components/ViewerCapabilities";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { apiErrorMessage } from "@/lib/api-errors";
import { formatMoney } from "@/lib/money";
import { updateWorkspaceSettingsAction } from "@/lib/server-actions";
import { cn } from "@/lib/utils";

function parseCap(value: string) {
  const trimmed = value.trim();
  if (!trimmed) return { ok: true as const, value: null };
  const parsed = Number(trimmed);
  if (!Number.isFinite(parsed) || parsed < 0) return { ok: false as const };
  return { ok: true as const, value: parsed };
}

type Edit =
  | { mode: "view"; notice: { ok: boolean; text: string } | null }
  | { mode: "edit"; input: string; error: string | null };

/** The workspace's monthly cap: what it is, how much of it is spent, whether the projection crosses it, and editing it in place. */
export function BudgetCap({
  initialCap,
  mtdSpend,
  projected,
  currency,
  settingsError,
}: {
  initialCap: number | null;
  mtdSpend: number;
  projected: number | null;
  currency: string | null;
  settingsError: string | null;
}) {
  const t = useTranslations("BudgetsPage");
  const router = useWorkspaceRouter();
  const { canAdminister } = useViewerCapabilities();
  const locale = useLocale();
  const fmt = (v: number) => formatMoney(v, currency, locale);
  const [cap, setCap] = useState(initialCap);
  const [edit, setEdit] = useState<Edit>({
    mode: "view",
    notice: settingsError ? { ok: false, text: settingsError } : null,
  });
  const [isPending, startTransition] = useTransition();

  const usedPct = cap && cap > 0 ? (mtdSpend / cap) * 100 : null;
  const projectedPct =
    cap && cap > 0 && projected != null ? (projected / cap) * 100 : null;

  const startEdit = () =>
    setEdit({
      mode: "edit",
      input: cap == null ? "" : String(cap),
      error: null,
    });

  const save = (event: FormEvent) => {
    event.preventDefault();
    if (edit.mode !== "edit") return;
    const parsed = parseCap(edit.input);
    if (!parsed.ok) {
      setEdit({ ...edit, error: t("capInvalid") });
      return;
    }
    if (parsed.value === cap) {
      setEdit({ mode: "view", notice: null });
      return;
    }
    startTransition(async () => {
      const result = await updateWorkspaceSettingsAction(parsed.value);
      const data = result.data;
      if (result.error || !data) {
        setEdit({
          ...edit,
          error: apiErrorMessage(result, t("capUpdateFailed")),
        });
        return;
      }
      // The API returns the cap as a decimal string.
      setCap(
        data.monthly_cap_usd == null ? null : Number(data.monthly_cap_usd)
      );
      setEdit({ mode: "view", notice: { ok: true, text: t("capUpdated") } });
      router.refresh();
    });
  };

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <BoardSectionHeader
        icon={<Gauge />}
        color="hsl(var(--foreground))"
        title={t("monthlyCap")}
        meta={
          canAdminister && edit.mode === "view" ? (
            <Button
              type="button"
              variant="ghost"
              size="xs"
              className="text-muted-foreground"
              onClick={startEdit}
            >
              <Pencil />
              {t("edit")}
            </Button>
          ) : undefined
        }
      />

      {edit.mode === "edit" ? (
        <form onSubmit={save} className="mt-2 flex flex-col gap-2">
          <label htmlFor="monthly-cap" className="sr-only">
            {t("capField", { currency: currency ?? "¤" })}
          </label>
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Input
                id="monthly-cap"
                inputMode="decimal"
                autoFocus
                value={edit.input}
                onChange={(e) =>
                  setEdit({ mode: "edit", input: e.target.value, error: null })
                }
                placeholder={t("capPlaceholder")}
                disabled={isPending}
                className="h-9 pr-12 tabular-nums"
              />
              {currency && (
                <span className="pointer-events-none absolute inset-y-0 right-3 flex items-center text-[12px] text-muted-foreground">
                  {currency}
                </span>
              )}
            </div>
            <Button
              type="submit"
              size="sm"
              className="h-9"
              isLoading={isPending}
            >
              {t("save")}
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-9"
              disabled={isPending}
              onClick={() => setEdit({ mode: "view", notice: null })}
            >
              {t("cancel")}
            </Button>
          </div>
          {edit.error ? (
            <StatusIndicator kind="failed" size="sm" className="text-[11.5px]">
              {edit.error}
            </StatusIndicator>
          ) : (
            <p className="text-[11.5px] text-muted-foreground">
              {t("capEditHint")}
            </p>
          )}
        </form>
      ) : (
        <div
          className={cn(
            "mt-2 font-semibold leading-none tracking-[-0.03em] tabular-nums",
            cap == null
              ? "text-[15px] text-muted-foreground"
              : "text-[28px] text-foreground"
          )}
        >
          {cap == null ? t("capNotSet") : fmt(cap)}
        </div>
      )}

      {edit.mode === "view" && (
        <p className="mt-2 text-[12.5px] text-muted-foreground">
          {cap == null ? t("capNoCap") : t("capDesc")}
        </p>
      )}

      {usedPct != null && cap != null && (
        <div className="mt-5">
          <div className="flex items-baseline justify-between text-[12px] tabular-nums">
            <span className="font-medium text-foreground">
              {t("capUsed", { amount: fmt(mtdSpend), cap: fmt(cap) })}
            </span>
            <span className={cn("font-medium", capTone(usedPct))}>
              {usedPct.toFixed(0)}%
            </span>
          </div>
          <CapMeter pct={usedPct} className="mt-2 h-[7px]" />
        </div>
      )}

      {projectedPct != null && projectedPct >= 80 && (
        <StatusIndicator
          kind={projectedPct >= 100 ? "failed" : "attention"}
          size="sm"
          className="mt-3 text-[12px] text-foreground"
        >
          {projectedPct >= 100
            ? t("hintOverCap", { pct: projectedPct.toFixed(0) })
            : t("hintNearCap", { pct: projectedPct.toFixed(0) })}
        </StatusIndicator>
      )}

      {!canAdminister && (
        <div className="mt-3">
          <AdminOnlyHint action="budgetCap" />
        </div>
      )}

      {edit.mode === "view" && edit.notice && (
        <StatusIndicator
          kind={edit.notice.ok ? "done" : "failed"}
          size="sm"
          className="mt-3 text-[11.5px]"
        >
          {edit.notice.text}
        </StatusIndicator>
      )}
    </div>
  );
}
