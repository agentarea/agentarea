"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import type { CustomHeader } from "./CustomHeadersList";
import { QueryParamRows, type QueryParamRow } from "./QueryParamRows";

export function CustomQueryParamsEditor({
  initial,
  saving,
  onSave,
  onCancel,
}: {
  initial: CustomHeader[];
  saving?: boolean;
  onSave: (rows: QueryParamRow[]) => Promise<void> | void;
  onCancel: () => void;
}) {
  const t = useTranslations("OpenAPIConnection");
  // Secret values come back masked: a blank value keeps the stored one.
  const [rows, setRows] = useState<QueryParamRow[]>(() =>
    initial.map((p) => ({
      name: p.name,
      value: p.secret ? "" : (p.value ?? ""),
      secret: p.secret,
    }))
  );
  const storedSecrets = new Set(initial.filter((p) => p.secret).map((p) => p.name));

  const handleSave = () =>
    onSave(
      rows
        .filter((r) => r.name.trim())
        .map((r) => ({ ...r, name: r.name.trim() }))
    );

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex items-center justify-between">
        <Label>{t("editQueryParams")}</Label>
        <Button
          type="button"
          variant="outline"
          size="xs"
          onClick={() => setRows([...rows, { name: "", value: "", secret: true }])}
        >
          <Plus className="mr-1" />
          {t("addHeader")}
        </Button>
      </div>

      {rows.length === 0 && (
        <p className="text-xs text-muted-foreground">{t("queryParamsEditorHint")}</p>
      )}

      <QueryParamRows rows={rows} onChange={setRows} keepSecretNames={storedSecrets} />

      <div className="flex gap-2 pt-1">
        <Button type="button" size="xs" onClick={handleSave} disabled={saving}>
          {saving ? t("saving") : t("saveQueryParams")}
        </Button>
        <Button type="button" size="xs" variant="outline" onClick={onCancel} disabled={saving}>
          {t("cancel")}
        </Button>
      </div>
    </div>
  );
}
