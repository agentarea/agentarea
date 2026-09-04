"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Lock, Plus, Trash2, Unlock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import type { CustomHeader } from "./CustomHeadersList";

interface HeaderRow {
  name: string;
  value: string;
}

const SAFE_HEADERS = new Set([
  "accept",
  "accept-charset",
  "accept-encoding",
  "accept-language",
  "cache-control",
  "content-type",
  "if-match",
  "if-none-match",
  "user-agent",
  "x-correlation-id",
  "x-request-id",
]);

function isSecretHeader(name: string) {
  return !SAFE_HEADERS.has(name.toLowerCase().trim());
}

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
  const removeRow = (i: number) => setRows(rows.filter((_, idx) => idx !== i));
  const updateRow = (i: number, field: keyof HeaderRow, val: string) => {
    const next = [...rows];
    next[i] = { ...next[i], [field]: val };
    setRows(next);
  };

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

      {rows.map((h, i) => {
        const secret = h.name.trim() ? isSecretHeader(h.name) : false;
        return (
          <div key={i} className="flex items-center gap-2">
            <Input
              placeholder={t("headerName")}
              value={h.name}
              onChange={(e) => updateRow(i, "name", e.target.value)}
              className="flex-1"
            />
            <div className="relative flex-1">
              <Input
                placeholder={secret ? t("secretValuePlaceholder") : t("headerValue")}
                value={h.value}
                onChange={(e) => updateRow(i, "value", e.target.value)}
                type={secret ? "password" : "text"}
                className="pr-8"
              />
              <div className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground">
                {secret ? <Lock className="h-3.5 w-3.5" /> : <Unlock className="h-3.5 w-3.5" />}
              </div>
            </div>
            <Button type="button" variant="ghost" size="xs" onClick={() => removeRow(i)}>
              <Trash2 />
            </Button>
          </div>
        );
      })}

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
