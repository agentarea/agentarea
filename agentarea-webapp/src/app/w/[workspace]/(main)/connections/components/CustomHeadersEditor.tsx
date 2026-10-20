"use client";

import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { CustomHeader } from "./CustomHeadersList";
import { HeaderRows, type HeaderRow } from "./HeaderRows";

/**
 * Rows to edit for stored headers. A secret comes back without its value, so
 * it starts blank (blank keeps the stored one). An empty list starts with one
 * row to fill in, so "Add" does not need a second click.
 */
export function toHeaderRows(stored: CustomHeader[]): HeaderRow[] {
  return stored.length > 0
    ? stored.map((h) => ({ name: h.name, value: h.secret ? "" : (h.value ?? "") }))
    : [{ name: "", value: "" }];
}

/** The rows worth saving: named ones, names trimmed. */
export function cleanHeaderRows(rows: HeaderRow[]): HeaderRow[] {
  return rows
    .filter((r) => r.name.trim())
    .map((r) => ({ name: r.name.trim(), value: r.value }));
}

/**
 * The header rows of an open editor. Save and Cancel live in the section
 * card's head, which owns the draft; this draws the rows and the Add button.
 */
export function CustomHeadersEditor({
  rows,
  onChange,
  stored,
  alwaysSecret,
}: {
  rows: HeaderRow[];
  onChange: (rows: HeaderRow[]) => void;
  /** What is saved now: its secrets keep their value when left blank. */
  stored: CustomHeader[];
  /** Every value is stored as a secret, whatever the header's name. */
  alwaysSecret?: boolean;
}) {
  const t = useTranslations("OpenAPIConnection");
  const storedSecrets = new Set(stored.filter((h) => h.secret).map((h) => h.name));

  return (
    <div className="space-y-3">
      {stored.length === 0 && <p className="note">{t("headersEditorHint")}</p>}
      <HeaderRows
        rows={rows}
        onChange={onChange}
        keepSecretNames={storedSecrets}
        alwaysSecret={alwaysSecret}
      />
      <div className="flex justify-end">
        <Button
          type="button"
          variant="ghost"
          size="xs"
          className="text-muted-foreground"
          onClick={() => onChange([...rows, { name: "", value: "" }])}
        >
          <Plus />
          {t("addHeader")}
        </Button>
      </div>
    </div>
  );
}
