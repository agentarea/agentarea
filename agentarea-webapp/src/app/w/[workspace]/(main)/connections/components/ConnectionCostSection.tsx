"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { Pencil } from "lucide-react";
import FormError from "@/components/FormError";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { apiErrorMessage, type ApiResultLike } from "@/lib/api-errors";
import {
  costToForm,
  formToCost,
  type CostDeclaration,
  type CostForm,
  type CostMode,
} from "../connection-cost";

const MODES: CostMode[] = [
  "connector",
  "per_call",
  "per_unit",
  "from_response",
  "free",
];

/**
 * What a call of a connection the workspace pays for costs, as a member sets it
 * (wiki ADR-0038 §2.3): per call, per unit, or read from a field of the response.
 * It wins over the connector's declaration and is what caps count. A connection
 * the platform pays for is priced by billing, so it shows nothing here.
 */
export function ConnectionCostSection({
  cost,
  managedBy,
  onSave,
  onSaved,
}: {
  cost: CostDeclaration | null | undefined;
  managedBy?: string | null;
  onSave: (cost: CostDeclaration | null) => Promise<ApiResultLike>;
  onSaved: () => void;
}) {
  const t = useTranslations("ConnectionCost");
  const [editing, setEditing] = useState(false);
  const [form, setForm] = useState<CostForm>(() => costToForm(cost));
  const [error, setError] = useState<string | null>(null);
  const [saving, startSaving] = useTransition();

  if (managedBy === "platform") return null;

  const current = costToForm(cost);
  const set = (patch: Partial<CostForm>) => setForm({ ...form, ...patch });
  const save = () =>
    startSaving(async () => {
      const result = await onSave(formToCost(form));
      if (result?.error) {
        setError(apiErrorMessage(result, t("saveFailed")));
        return;
      }
      setError(null);
      setEditing(false);
      onSaved();
    });

  return (
    <div className="space-y-2">
      <div className="flex items-center justify-between">
        <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
          {t("title")}
        </div>
        {!editing && (
          <Button
            size="xs"
            variant="outline"
            onClick={() => {
              setForm(costToForm(cost));
              setEditing(true);
            }}
          >
            <Pencil className="mr-1" />
            {t("edit")}
          </Button>
        )}
      </div>

      {!editing ? (
        <p className="text-sm text-muted-foreground">
          {t(`summary.${current.mode}`, {
            amount: current.amount,
            currency: current.currency,
            unit: current.unit,
            quantity: current.quantity,
            path: current.path,
          })}
        </p>
      ) : (
        <div className="space-y-3 rounded-lg border p-4">
          <p className="text-xs text-muted-foreground">{t("hint")}</p>
          <div className="space-y-1.5">
            <Label>{t("mode")}</Label>
            <Select
              value={form.mode}
              onValueChange={(mode) => set({ mode: mode as CostMode })}
            >
              <SelectTrigger className="w-full sm:w-72">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {MODES.map((mode) => (
                  <SelectItem key={mode} value={mode}>
                    {t(`modes.${mode}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {(form.mode === "per_call" || form.mode === "per_unit") && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>{t("amount")}</Label>
                <Input
                  inputMode="decimal"
                  value={form.amount}
                  onChange={(e) => set({ amount: e.target.value })}
                  placeholder="0.01"
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t("currency")}</Label>
                <Input
                  value={form.currency}
                  onChange={(e) => set({ currency: e.target.value })}
                  placeholder="USD"
                  maxLength={4}
                />
              </div>
            </div>
          )}

          {form.mode === "per_unit" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>{t("unit")}</Label>
                <Input
                  value={form.unit}
                  onChange={(e) => set({ unit: e.target.value })}
                  placeholder={t("unitPlaceholder")}
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t("quantity")}</Label>
                <Input
                  className="font-mono text-xs"
                  value={form.quantity}
                  onChange={(e) => set({ quantity: e.target.value })}
                  placeholder="num_pages | $.usage.pages"
                />
              </div>
            </div>
          )}

          {form.mode === "from_response" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label>{t("path")}</Label>
                <Input
                  className="font-mono text-xs"
                  value={form.path}
                  onChange={(e) => set({ path: e.target.value })}
                  placeholder="$.cost"
                />
              </div>
              <div className="space-y-1.5">
                <Label>{t("currency")}</Label>
                <Input
                  value={form.currency}
                  onChange={(e) => set({ currency: e.target.value })}
                  placeholder="USD"
                  maxLength={4}
                />
              </div>
            </div>
          )}

          {error && <FormError>{error}</FormError>}
          <div className="flex justify-end gap-2">
            <Button
              size="xs"
              variant="outline"
              onClick={() => setEditing(false)}
              disabled={saving}
            >
              {t("cancel")}
            </Button>
            <Button size="xs" onClick={save} disabled={saving}>
              {saving ? t("saving") : t("save")}
            </Button>
          </div>
        </div>
      )}
    </div>
  );
}
