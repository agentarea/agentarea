"use client";

import { useTranslations } from "next-intl";
import { Lock, Trash2, Unlock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";

/** A name / value pair whose value can be locked as a secret. */
export interface SecretRow {
  name: string;
  value: string;
  secret: boolean;
}

/**
 * Editable name / value rows with a lock toggle per row: query parameters,
 * environment variables. Placeholders default to the query-parameter ones.
 */
export function SecretRows({
  rows,
  onChange,
  keepSecretNames,
  namePlaceholder,
  valuePlaceholder,
  nameClassName,
}: {
  rows: SecretRow[];
  onChange: (rows: SecretRow[]) => void;
  // Secrets already stored: a blank value keeps the stored one.
  keepSecretNames?: ReadonlySet<string>;
  namePlaceholder?: string;
  valuePlaceholder?: string;
  nameClassName?: string;
}) {
  const t = useTranslations("OpenAPIConnection");

  const update = (i: number, patch: Partial<SecretRow>) =>
    onChange(rows.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));

  return (
    <>
      {rows.map((row, i) => (
        <div key={i} className="flex items-center gap-2">
          <Input
            placeholder={namePlaceholder ?? t("queryParamName")}
            value={row.name}
            onChange={(e) => update(i, { name: e.target.value })}
            className={cn("flex-1", nameClassName)}
          />
          <div className="relative flex-1">
            <Input
              placeholder={
                row.secret && keepSecretNames?.has(row.name.trim())
                  ? t("secretValuePlaceholder")
                  : (valuePlaceholder ?? t("queryParamValue"))
              }
              value={row.value}
              onChange={(e) => update(i, { value: e.target.value })}
              type={row.secret ? "password" : "text"}
              className="pr-8"
            />
            <Button
              type="button"
              variant="ghost"
              size="xs"
              className="absolute right-1 top-1/2 -translate-y-1/2 text-muted-foreground"
              onClick={() => update(i, { secret: !row.secret })}
              aria-pressed={row.secret}
              aria-label={t("toggleSecret")}
              title={t("toggleSecret")}
            >
              {row.secret ? <Lock /> : <Unlock />}
            </Button>
          </div>
          <Button
            type="button"
            variant="ghost"
            size="xs"
            onClick={() => onChange(rows.filter((_, idx) => idx !== i))}
          >
            <Trash2 />
          </Button>
        </div>
      ))}
    </>
  );
}
