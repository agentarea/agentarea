"use client";

import { useTranslations } from "next-intl";
import { Lock, Trash2, Unlock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export interface QueryParamRow {
  name: string;
  value: string;
  secret: boolean;
}

export function QueryParamRows({
  rows,
  onChange,
  keepSecretNames,
}: {
  rows: QueryParamRow[];
  onChange: (rows: QueryParamRow[]) => void;
  // Secret params already stored: a blank value keeps the stored one.
  keepSecretNames?: ReadonlySet<string>;
}) {
  const t = useTranslations("OpenAPIConnection");

  const update = (i: number, patch: Partial<QueryParamRow>) =>
    onChange(rows.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));

  return (
    <>
      {rows.map((row, i) => (
        <div key={i} className="flex items-center gap-2">
          <Input
            placeholder={t("queryParamName")}
            value={row.name}
            onChange={(e) => update(i, { name: e.target.value })}
            className="flex-1"
          />
          <div className="relative flex-1">
            <Input
              placeholder={
                row.secret && keepSecretNames?.has(row.name.trim())
                  ? t("secretValuePlaceholder")
                  : t("queryParamValue")
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
