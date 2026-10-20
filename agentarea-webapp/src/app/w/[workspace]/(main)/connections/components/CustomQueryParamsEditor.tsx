"use client";

import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
import { Button } from "@/components/ui/button";
import type { CustomHeader } from "./CustomHeadersList";
import { SecretRows, type SecretRow } from "./SecretRows";

/**
 * Rows to edit for stored query parameters. A secret comes back without its
 * value, so it starts blank (blank keeps the stored one). An empty list starts
 * with one row to fill in, so "Add" does not need a second click.
 */
export function toQueryParamRows(stored: CustomHeader[]): SecretRow[] {
  return stored.length > 0
    ? stored.map((p) => ({
        name: p.name,
        value: p.secret ? "" : (p.value ?? ""),
        secret: p.secret,
      }))
    : [{ name: "", value: "", secret: true }];
}

/** The rows worth saving: named ones, names trimmed. */
export function cleanQueryParamRows(rows: SecretRow[]): SecretRow[] {
  return rows.filter((r) => r.name.trim()).map((r) => ({ ...r, name: r.name.trim() }));
}

/**
 * The parameter rows of an open editor. Save and Cancel live in the section
 * card's head, which owns the draft; this draws the rows and the Add button.
 */
export function CustomQueryParamsEditor({
  rows,
  onChange,
  stored,
}: {
  rows: SecretRow[];
  onChange: (rows: SecretRow[]) => void;
  /** What is saved now: its secrets keep their value when left blank. */
  stored: CustomHeader[];
}) {
  const t = useTranslations("OpenAPIConnection");
  const storedSecrets = new Set(stored.filter((p) => p.secret).map((p) => p.name));

  return (
    <div className="space-y-3">
      {stored.length === 0 && <p className="note">{t("queryParamsEditorHint")}</p>}
      <SecretRows rows={rows} onChange={onChange} keepSecretNames={storedSecrets} />
      <div className="flex justify-end">
        <Button
          type="button"
          variant="ghost"
          size="xs"
          className="text-muted-foreground"
          onClick={() => onChange([...rows, { name: "", value: "", secret: true }])}
        >
          <Plus />
          {t("addHeader")}
        </Button>
      </div>
    </div>
  );
}
