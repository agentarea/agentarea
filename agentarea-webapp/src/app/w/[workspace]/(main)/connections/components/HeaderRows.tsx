"use client";

import { useTranslations } from "next-intl";
import { Lock, Trash2, Unlock } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

export interface HeaderRow {
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

/** Any header outside the known-harmless set is stored encrypted. */
export function isSecretHeader(name: string) {
  return !SAFE_HEADERS.has(name.toLowerCase().trim());
}

export function HeaderRows({
  rows,
  onChange,
  keepSecretNames,
}: {
  rows: HeaderRow[];
  onChange: (rows: HeaderRow[]) => void;
  // Secret headers already stored: a blank value keeps the stored one.
  keepSecretNames?: ReadonlySet<string>;
}) {
  const t = useTranslations("OpenAPIConnection");

  const update = (i: number, patch: Partial<HeaderRow>) =>
    onChange(rows.map((row, idx) => (idx === i ? { ...row, ...patch } : row)));

  return (
    <>
      {rows.map((row, i) => {
        const secret = row.name.trim() ? isSecretHeader(row.name) : false;
        return (
          <div key={i} className="flex items-center gap-2">
            <Input
              placeholder={t("headerName")}
              value={row.name}
              onChange={(e) => update(i, { name: e.target.value })}
              className="flex-1"
            />
            <div className="relative flex-1">
              <Input
                placeholder={
                  secret && keepSecretNames?.has(row.name.trim())
                    ? t("secretValuePlaceholder")
                    : t("headerValue")
                }
                value={row.value}
                onChange={(e) => update(i, { value: e.target.value })}
                type={secret ? "password" : "text"}
                className="pr-8"
              />
              <div className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground">
                {secret ? (
                  <Lock className="h-3.5 w-3.5" />
                ) : (
                  <Unlock className="h-3.5 w-3.5" />
                )}
              </div>
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
        );
      })}
    </>
  );
}
