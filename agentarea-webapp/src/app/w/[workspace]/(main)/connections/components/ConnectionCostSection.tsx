"use client";

import { useState, useTransition } from "react";
import { useTranslations } from "next-intl";
import { Wallet } from "lucide-react";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import { SectionCard, SectionCardHead } from "@/components/Overview/OverviewCard";
import { Input } from "@/components/ui/input";
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
import { SectionEditAction } from "./SectionEditAction";

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
 *
 * A section card of the connection overview, edited in place like its headers:
 * Edit, Cancel and Save sit in the card head.
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

  const currencyField = (
    <div className="space-y-1.5">
      <FormLabel htmlFor="cost-currency">{t("currency")}</FormLabel>
      <Input
        id="cost-currency"
        value={form.currency}
        onChange={(e) => set({ currency: e.target.value })}
        placeholder="USD"
        maxLength={4}
      />
    </div>
  );

  return (
    <SectionCard>
      <SectionCardHead
        icon={<Wallet />}
        title={t("title")}
        action={
          <SectionEditAction
            open={editing}
            hasRows
            busy={saving}
            onOpen={() => {
              setForm(costToForm(cost));
              setError(null);
              setEditing(true);
            }}
            onCancel={() => setEditing(false)}
            onSave={save}
            saveLabel={t("saveCost")}
          />
        }
      />

      {!editing ? (
        <p className="px-[15px] py-3 text-[12.5px]">
          {t(`summary.${current.mode}`, {
            amount: current.amount,
            currency: current.currency,
            unit: current.unit,
            quantity: current.quantity,
            path: current.path,
          })}
        </p>
      ) : (
        <div className="space-y-3 px-[15px] py-3">
          <p className="note">{t("hint")}</p>
          <div className="space-y-1.5">
            <FormLabel htmlFor="cost-mode">{t("mode")}</FormLabel>
            <Select
              value={form.mode}
              onValueChange={(mode) => set({ mode: mode as CostMode })}
            >
              <SelectTrigger id="cost-mode" className="w-full">
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
                <FormLabel htmlFor="cost-amount">{t("amount")}</FormLabel>
                <Input
                  id="cost-amount"
                  inputMode="decimal"
                  value={form.amount}
                  onChange={(e) => set({ amount: e.target.value })}
                  placeholder="0.01"
                />
              </div>
              {currencyField}
            </div>
          )}

          {form.mode === "per_unit" && (
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <FormLabel htmlFor="cost-unit">{t("unit")}</FormLabel>
                <Input
                  id="cost-unit"
                  value={form.unit}
                  onChange={(e) => set({ unit: e.target.value })}
                  placeholder={t("unitPlaceholder")}
                />
              </div>
              <div className="space-y-1.5">
                <FormLabel htmlFor="cost-quantity">{t("quantity")}</FormLabel>
                <Input
                  id="cost-quantity"
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
                <FormLabel htmlFor="cost-path">{t("path")}</FormLabel>
                <Input
                  id="cost-path"
                  className="font-mono text-xs"
                  value={form.path}
                  onChange={(e) => set({ path: e.target.value })}
                  placeholder="$.cost"
                />
              </div>
              {currencyField}
            </div>
          )}

          {error && <FormError>{error}</FormError>}
        </div>
      )}
    </SectionCard>
  );
}
