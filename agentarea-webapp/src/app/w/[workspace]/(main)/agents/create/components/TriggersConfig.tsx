import React, { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Trash2, Zap } from "lucide-react";
import type { TriggerSpec } from "@/api/client/types.gen";
import AccordionControl from "@/components/AccordionControl";
import FormLabel from "@/components/FormLabel/FormLabel";
import SectionLoadError from "@/components/SectionLoadError";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import Note from "@/components/ui/note";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { resolveSession } from "@/lib/sourceTypes";
import { SessionSetting } from "@/app/w/[workspace]/(main)/triggers/components/SessionSetting";
import { renderTriggerIcon } from "@/app/w/[workspace]/(main)/triggers/components/triggerDisplay";
import { CronScheduler } from "@/app/w/[workspace]/(main)/triggers/create/CronScheduler";
import type { StreamOptions } from "@/app/w/[workspace]/(main)/triggers/create/streamOptions";
import { TIMEZONES } from "@/app/w/[workspace]/(main)/triggers/create/timezones";
import { requiresTaskText } from "@/app/w/[workspace]/(main)/triggers/create/triggerShape";

/** A trigger being authored; the key keeps its inputs attached across removals. */
export type TriggerDraft = { key: string; spec: TriggerSpec };

let nextDraftKey = 0;
export const toTriggerDrafts = (specs: TriggerSpec[]): TriggerDraft[] =>
  specs.map((spec) => ({ key: String(nextDraftKey++), spec }));

/** What a trigger can be: a schedule, or a subscription to a stream. */
const TRIGGER_TYPES = ["cron", "stream"] as const;

/** A stream trigger cannot fire until it is bound to a stream. */
export function hasIncompleteTriggers(drafts: TriggerDraft[]): boolean {
  return drafts.some(
    ({ spec }) => spec.trigger_type === "stream" && !spec.stream_id
  );
}

function specFor(
  type: (typeof TRIGGER_TYPES)[number],
  name: string
): TriggerSpec {
  return {
    name,
    trigger_type: type,
    enabled: true,
    task_parameters: {},
    ...(type === "cron" ? { cron_expression: null, timezone: "UTC" } : {}),
  };
}

type TriggersConfigProps = {
  /** The streams a stream trigger can bind to. */
  streams: StreamOptions;
  drafts: TriggerDraft[];
  onDraftsChange: React.Dispatch<React.SetStateAction<TriggerDraft[]>>;
  showErrors: boolean;
};

const TriggersConfig = ({
  streams,
  drafts,
  onDraftsChange,
  showErrors,
}: TriggersConfigProps) => {
  const [accordionValue, setAccordionValue] = useState<string>("triggers");
  const t = useTranslations("AgentsPage.create");
  const tTrigger = useTranslations("TriggersPage.create");
  const tType = useTranslations("TriggersPage.type");

  // Returns the previous list when nothing changed: CronScheduler reports its
  // value on every render.
  const patch = (key: string, changes: Partial<TriggerSpec>) =>
    onDraftsChange((previous) => {
      const draft = previous.find((d) => d.key === key);
      if (
        !draft ||
        Object.entries(changes).every(
          ([field, value]) => draft.spec[field as keyof TriggerSpec] === value
        )
      )
        return previous;
      return previous.map((d) =>
        d.key === key ? { key, spec: { ...d.spec, ...changes } } : d
      );
    });

  const dropdownItems = useMemo(
    () =>
      TRIGGER_TYPES.map((type) => ({
        id: type,
        label: tType(type),
        icon: renderTriggerIcon({ trigger_type: type }, "h-4 w-4"),
      })),
    [tType]
  );

  const addTrigger = (type: string) => {
    const known = TRIGGER_TYPES.find((item) => item === type);
    if (!known) return;
    onDraftsChange((previous) => [
      ...previous,
      ...toTriggerDrafts([specFor(known, tType(known))]),
    ]);
  };

  const title = (
    <FormLabel icon={Zap} className="cursor-pointer">
      {t("agentTriggers")}
    </FormLabel>
  );

  return (
    <AccordionControl
      id="triggers"
      accordionValue={accordionValue}
      setAccordionValue={setAccordionValue}
      title={title}
      note={<p>{t("agentTriggersNote")}</p>}
      addText={t("trigger")}
      onAdd={addTrigger}
      dropdownItems={dropdownItems}
    >
      <div className="space-y-3">
        {streams.error &&
          drafts.some(({ spec }) => spec.trigger_type === "stream") && (
            <SectionLoadError message={streams.error} />
          )}
        {drafts.map(({ key, spec }) => {
          const taskText = String(spec.task_parameters?.text ?? "");
          const taskTextRequired = requiresTaskText(spec.trigger_type);
          const stream = streams.items.find(
            (item) => item.id === spec.stream_id
          );

          return (
            <div
              key={key}
              className="space-y-4 rounded-md border bg-card p-3"
            >
              <div className="flex items-center gap-2">
                <span className="flex h-4 w-4 shrink-0 items-center justify-center text-muted-foreground">
                  {renderTriggerIcon(spec, "h-4 w-4")}
                </span>
                <span className="truncate text-sm font-medium">
                  {tType(spec.trigger_type)}
                </span>
                <div className="ml-auto flex items-center gap-2">
                  <Switch
                    id={`trigger-enabled-${key}`}
                    size="xs"
                    checked={spec.enabled ?? true}
                    onCheckedChange={(enabled) => patch(key, { enabled })}
                  />
                  <label
                    htmlFor={`trigger-enabled-${key}`}
                    className="cursor-pointer text-xs text-muted-foreground"
                  >
                    {t("triggerEnabled")}
                  </label>
                  <Button
                    type="button"
                    variant="ghost"
                    size="icon"
                    onClick={() =>
                      onDraftsChange((previous) =>
                        previous.filter((d) => d.key !== key)
                      )
                    }
                    className="h-4 w-4 flex-shrink-0 text-muted-foreground/60 hover:bg-transparent hover:text-red-500"
                    aria-label={t("removeTrigger")}
                  >
                    <Trash2 />
                  </Button>
                </div>
              </div>

              <div className="grid gap-2">
                <FormLabel htmlFor={`trigger-name-${key}`} required>
                  {tTrigger("automationName")}
                </FormLabel>
                <Input
                  id={`trigger-name-${key}`}
                  value={spec.name}
                  onChange={(event) => patch(key, { name: event.target.value })}
                  placeholder={tTrigger("automationNamePlaceholder")}
                  required
                />
              </div>

              {spec.trigger_type === "cron" && (
                <>
                  <div className="grid grid-cols-[minmax(0,1fr)] gap-2">
                    <FormLabel required>{tTrigger("schedule")}</FormLabel>
                    <CronScheduler
                      name={`trigger-cron-${key}`}
                      defaultValue={spec.cron_expression ?? ""}
                      onChange={(cron_expression) =>
                        patch(key, { cron_expression })
                      }
                    />
                  </div>
                  <div className="grid gap-2 md:max-w-sm">
                    <FormLabel htmlFor={`trigger-timezone-${key}`}>
                      {tTrigger("timezone")}
                    </FormLabel>
                    <Select
                      value={spec.timezone ?? "UTC"}
                      onValueChange={(timezone) => patch(key, { timezone })}
                    >
                      <SelectTrigger id={`trigger-timezone-${key}`}>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        {Array.from(
                          new Set<string>([
                            ...TIMEZONES,
                            ...(spec.timezone ? [spec.timezone] : []),
                          ])
                        ).map((timezone) => (
                          <SelectItem key={timezone} value={timezone}>
                            {timezone}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </>
              )}

              {spec.trigger_type === "stream" && (
                <>
                  <div className="grid gap-2 md:max-w-sm">
                    <FormLabel htmlFor={`trigger-stream-${key}`} required>
                      {tTrigger("stream")}
                    </FormLabel>
                    <Select
                      value={spec.stream_id ?? ""}
                      onValueChange={(stream_id) => patch(key, { stream_id })}
                      disabled={streams.error !== null}
                    >
                      <SelectTrigger id={`trigger-stream-${key}`}>
                        <SelectValue
                          placeholder={
                            streams.items.length === 0
                              ? tTrigger("noStreams")
                              : undefined
                          }
                        />
                      </SelectTrigger>
                      <SelectContent>
                        {streams.items.map((item) => (
                          <SelectItem key={item.id} value={item.id}>
                            {item.name}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {showErrors && !spec.stream_id && (
                      <p role="alert" className="text-sm text-destructive">
                        {t("triggerStreamRequired")}
                      </p>
                    )}
                  </div>
                  <SessionSetting
                    id={`trigger-session-${key}`}
                    value={resolveSession(
                      spec.session,
                      stream?.continuesSessions ?? false
                    )}
                    onChange={(session) => patch(key, { session })}
                  />
                </>
              )}

              <div className="grid gap-2">
                <FormLabel
                  htmlFor={`trigger-task-${key}`}
                  required={taskTextRequired}
                  optional={!taskTextRequired}
                >
                  {tTrigger("taskInstructions")}
                </FormLabel>
                {spec.trigger_type === "stream" && (
                  <p className="text-xs text-muted-foreground">
                    {tTrigger("taskTextFromStream")}
                  </p>
                )}
                <Textarea
                  id={`trigger-task-${key}`}
                  value={taskText}
                  onChange={(event) =>
                    patch(key, {
                      task_parameters: {
                        ...spec.task_parameters,
                        text: event.target.value,
                      },
                    })
                  }
                  placeholder={tTrigger("taskTextPlaceholder")}
                  rows={3}
                  required={taskTextRequired}
                />
              </div>
            </div>
          );
        })}

        {drafts.length === 0 && (
          <Note className="mt-2 cursor-default items-center gap-2 rounded-md border p-3 text-center text-xs text-muted-foreground">
            <p>{t("noTriggers")}</p>
          </Note>
        )}
      </div>
    </AccordionControl>
  );
};

export default TriggersConfig;
