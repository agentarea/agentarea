"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import type { CustomHeader } from "./CustomHeadersList";
import { HeaderRows, type HeaderRow } from "./HeaderRows";

export interface CustomHeadersEditorProps {
  initial: CustomHeader[];
  saving?: boolean;
  onSave: (rows: HeaderRow[]) => Promise<void> | void;
  onCancel: () => void;
}

export function CustomHeadersEditor({
  initial,
  saving,
  onSave,
  onCancel,
}: CustomHeadersEditorProps) {
  const t = useTranslations("OpenAPIConnection");
  // Existing secret headers come back without value (masked); preserve name
  // and let the user re-enter the value to keep it, leave blank to keep masked.
  const [rows, setRows] = useState<HeaderRow[]>(() =>
    initial.map((h) => ({ name: h.name, value: h.secret ? "" : h.value ?? "" }))
  );

  const addRow = () => setRows([...rows, { name: "", value: "" }]);
  const storedSecrets = new Set(
    initial.filter((h) => h.secret).map((h) => h.name)
  );

  const handleSave = () => {
    const cleaned = rows
      .filter((r) => r.name.trim())
      .map((r) => ({ name: r.name.trim(), value: r.value }));
    onSave(cleaned);
  };

  return (
    <div className="space-y-3 rounded-lg border p-4">
      <div className="flex items-center justify-between">
        <Label>{t("editHeaders")}</Label>
        <Button type="button" variant="outline" size="xs" onClick={addRow}>
          <Plus className="mr-1" />
          {t("addHeader")}
        </Button>
      </div>

      {rows.length === 0 && (
        <p className="text-xs text-muted-foreground">{t("headersEditorHint")}</p>
      )}

      <HeaderRows rows={rows} onChange={setRows} keepSecretNames={storedSecrets} />

      <div className="flex gap-2 pt-1">
        <Button type="button" size="xs" onClick={handleSave} disabled={saving}>
          {saving ? t("saving") : t("saveHeaders")}
        </Button>
        <Button type="button" size="xs" variant="outline" onClick={onCancel} disabled={saving}>
          {t("cancel")}
        </Button>
      </div>
    </div>
  );
}
