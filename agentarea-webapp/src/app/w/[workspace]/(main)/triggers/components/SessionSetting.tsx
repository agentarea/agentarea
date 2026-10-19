"use client";

import { useTranslations } from "next-intl";
import { MessagesSquare } from "lucide-react";
import type { TriggerCreate } from "@/api/client/types.gen";
import FormLabel from "@/components/FormLabel/FormLabel";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { SESSION_IDLE_TIMEOUTS, type ResolvedSession } from "@/lib/sourceTypes";

export type TriggerSession = NonNullable<TriggerCreate["session"]>;

/**
 * What a stream trigger does with the next event of the same session (ADR-0040
 * §4): join the task that is waiting for it, or start a task of its own. With
 * `name`, the value also posts with a native form as `<name>_continue` and
 * `<name>_idle_timeout`.
 */
export function SessionSetting({
  id,
  value,
  onChange,
  name,
}: {
  id: string;
  value: ResolvedSession;
  onChange: (value: ResolvedSession) => void;
  name?: string;
}) {
  const t = useTranslations("TriggersPage.create.session");
  const timeouts = SESSION_IDLE_TIMEOUTS.includes(value.idle_timeout)
    ? SESSION_IDLE_TIMEOUTS
    : [...SESSION_IDLE_TIMEOUTS, value.idle_timeout];

  return (
    <div className="grid gap-3 md:max-w-sm">
      {name && (
        <>
          <input
            type="hidden"
            name={`${name}_continue`}
            value={String(value.continue)}
          />
          <input
            type="hidden"
            name={`${name}_idle_timeout`}
            value={value.idle_timeout}
          />
        </>
      )}
      <div className="flex items-start gap-3">
        <Switch
          id={`${id}-continue`}
          size="xs"
          className="mt-0.5"
          checked={value.continue}
          onCheckedChange={(checked) =>
            onChange({ ...value, continue: checked })
          }
        />
        <div className="grid gap-1">
          <FormLabel htmlFor={`${id}-continue`} icon={MessagesSquare}>
            {t("continue")}
          </FormLabel>
          <p className="text-xs text-muted-foreground">
            {value.continue ? t("continueHint") : t("eachEventHint")}
          </p>
        </div>
      </div>
      {value.continue && (
        <div className="grid gap-2">
          <FormLabel htmlFor={`${id}-idle-timeout`}>
            {t("idleTimeout")}
          </FormLabel>
          <Select
            value={value.idle_timeout}
            onValueChange={(idle_timeout) =>
              onChange({ ...value, idle_timeout })
            }
          >
            <SelectTrigger id={`${id}-idle-timeout`}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {timeouts.map((timeout) => (
                <SelectItem key={timeout} value={timeout}>
                  {timeout}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
    </div>
  );
}
