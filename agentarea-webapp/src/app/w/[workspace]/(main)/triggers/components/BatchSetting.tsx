"use client";

import { useTranslations } from "next-intl";
import { Layers } from "lucide-react";
import type { TriggerBatchWindow } from "@/api/client/types.gen";
import FormLabel from "@/components/FormLabel/FormLabel";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";

const BATCH_WINDOWS = ["1m", "5m", "15m", "30m", "1h", "6h", "12h", "1d"];
const NO_WINDOW = "none";
const DEFAULT_BATCH: TriggerBatchWindow = { window: "1h", max_events: null };

/**
 * Whether a stream trigger fires once per event or once for a batch of them
 * (ADR-0040 §4): the batch fires when its window has passed or it holds
 * `max_events`, whichever comes first. Null is per event. With `name`, the value
 * also posts with a native form as JSON, empty when off.
 */
export function BatchSetting({
  id,
  value,
  onChange,
  name,
}: {
  id: string;
  value: TriggerBatchWindow | null;
  onChange: (value: TriggerBatchWindow | null) => void;
  name?: string;
}) {
  const t = useTranslations("TriggersPage.create.batch");
  const current = value?.window ?? NO_WINDOW;
  const windows =
    current === NO_WINDOW || BATCH_WINDOWS.includes(current)
      ? BATCH_WINDOWS
      : [...BATCH_WINDOWS, current];

  return (
    <div className="grid gap-3 md:max-w-sm">
      {name && (
        <input
          type="hidden"
          name={name}
          value={value ? JSON.stringify(value) : ""}
        />
      )}
      <div className="flex items-start gap-3">
        <Switch
          id={`${id}-on`}
          size="xs"
          className="mt-0.5 shrink-0"
          checked={value !== null}
          onCheckedChange={(checked) =>
            onChange(checked ? DEFAULT_BATCH : null)
          }
        />
        <div className="grid gap-1">
          <FormLabel htmlFor={`${id}-on`} icon={Layers}>
            {t("title")}
          </FormLabel>
          <p className="text-xs text-muted-foreground">
            {value ? t("onHint") : t("offHint")}
          </p>
        </div>
      </div>
      {value && (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="grid gap-2">
            <FormLabel htmlFor={`${id}-window`}>{t("window")}</FormLabel>
            <Select
              value={current}
              onValueChange={(next) =>
                onChange({
                  ...value,
                  window: next === NO_WINDOW ? null : next,
                })
              }
            >
              <SelectTrigger id={`${id}-window`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_WINDOW}>{t("noWindow")}</SelectItem>
                {windows.map((option) => (
                  <SelectItem key={option} value={option}>
                    {option}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className="grid gap-2">
            <FormLabel htmlFor={`${id}-max-events`}>
              {t("maxEvents")}
            </FormLabel>
            <Input
              id={`${id}-max-events`}
              type="number"
              inputMode="numeric"
              min={2}
              className="tabular-nums"
              placeholder={t("maxEventsPlaceholder")}
              value={value.max_events ?? ""}
              onChange={(event) => {
                const count = parseInt(event.target.value, 10);
                onChange({
                  ...value,
                  max_events: Number.isNaN(count) ? null : count,
                });
              }}
            />
          </div>
        </div>
      )}
    </div>
  );
}
