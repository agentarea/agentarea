import React, { useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Trash2, Zap } from "lucide-react";
import type { TriggerSpec } from "@/api/client/types.gen";
import AccordionControl from "@/components/AccordionControl";
import FormLabel from "@/components/FormLabel/FormLabel";
import { SecretSelect } from "@/components/SecretSelect";
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
import { useAttachableResources } from "@/hooks/use-attachable-resources";
import {
  findTriggerCatalogEntry,
  getTriggerLane,
  renderTriggerIcon,
} from "@/app/w/[workspace]/(main)/triggers/components/triggerDisplay";
import type { TriggerCatalogEntry } from "@/app/w/[workspace]/(main)/triggers/create/actions";
import { CronScheduler } from "@/app/w/[workspace]/(main)/triggers/create/CronScheduler";
import { TIMEZONES } from "@/app/w/[workspace]/(main)/triggers/create/timezones";
import { requiresTaskText } from "@/app/w/[workspace]/(main)/triggers/create/triggerShape";

/** A trigger being authored; the key keeps its inputs attached across removals. */
export type TriggerDraft = { key: string; spec: TriggerSpec };

let nextDraftKey = 0;
export const toTriggerDrafts = (specs: TriggerSpec[]): TriggerDraft[] =>
  specs.map((spec) => ({ key: String(nextDraftKey++), spec }));

const catalogEntryFor = (spec: TriggerSpec, catalog: TriggerCatalogEntry[]) =>
  findTriggerCatalogEntry(spec, catalog) as TriggerCatalogEntry | undefined;

const credentialSecretId = (spec: TriggerSpec, key: string): string => {
  const value = spec.channel_credentials?.[key];
  return value && typeof value === "object" && "secret_id" in value
    ? String(value.secret_id)
    : "";
};

/** A channel cannot receive anything until each of its credentials is picked. */
function missingCredentials(
  spec: TriggerSpec,
  entry: TriggerCatalogEntry | undefined
): string[] {
  if (!entry) return [];
  const required =
    getTriggerLane(spec, entry) === "channel" || !!entry.data_extractor;
  if (!required) return [];
  return (entry.credential_fields ?? [])
    .filter((field) => !credentialSecretId(spec, field.key))
    .map((field) => field.key);
}

export function hasIncompleteTriggers(
  drafts: TriggerDraft[],
  catalog: TriggerCatalogEntry[]
): boolean {
  return drafts.some(
    ({ spec }) =>
      missingCredentials(spec, catalogEntryFor(spec, catalog)).length > 0
  );
}

function specFromEntry(entry: TriggerCatalogEntry): TriggerSpec {
  return {
    name: entry.name,
    trigger_type: entry.backend_type,
    enabled: true,
    task_parameters: {},
    ...(entry.backend_type === "cron"
      ? { cron_expression: entry.default_cron ?? null, timezone: "UTC" }
      : {}),
    ...(entry.backend_type === "webhook"
      ? { webhook_type: entry.webhook_type || "generic" }
      : {}),
    ...(entry.default_methods ? { allowed_methods: entry.default_methods } : {}),
    ...(entry.data_extractor ? { data_extractor: entry.data_extractor } : {}),
  };
}

type TriggersConfigProps = {
  /** `null` when the trigger catalog could not be loaded. */
  catalog: TriggerCatalogEntry[] | null;
  drafts: TriggerDraft[];
  onDraftsChange: React.Dispatch<React.SetStateAction<TriggerDraft[]>>;
  showErrors: boolean;
};

const TriggersConfig = ({
  catalog,
  drafts,
  onDraftsChange,
  showErrors,
}: TriggersConfigProps) => {
  const [accordionValue, setAccordionValue] = useState<string>("triggers");
  const t = useTranslations("AgentsPage.create");
  const tTrigger = useTranslations("TriggersPage.create");
  const resources = useAttachableResources({ withSecrets: true });
  const secretsFailed = resources.failed.includes("secrets");

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
      (catalog ?? []).map((entry) => ({
        id: entry.id,
        label: entry.name,
        icon: renderTriggerIcon(entry, undefined, "h-4 w-4"),
      })),
    [catalog]
  );

  const addTrigger = (entryId: string) => {
    const entry = catalog?.find((e) => e.id === entryId);
    if (!entry) return;
    onDraftsChange((previous) => [
      ...previous,
      ...toTriggerDrafts([specFromEntry(entry)]),
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
        {catalog === null && (
          <p role="alert" className="text-sm text-destructive">
            {tTrigger("catalogLoadFailed")}
          </p>
        )}
        {drafts.map(({ key, spec }) => {
          const entry = catalogEntryFor(spec, catalog ?? []);
          const taskText = String(spec.task_parameters?.text ?? "");
          const taskTextRequired = requiresTaskText(
            spec.trigger_type,
            spec.data_extractor
          );
          const missing = showErrors ? missingCredentials(spec, entry) : [];
          const lane = getTriggerLane(spec, entry);

          return (
            <div
              key={key}
              className="space-y-4 rounded-md border bg-card p-3"
            >
              <div className="flex items-center gap-2">
                <span className="flex h-4 w-4 shrink-0 items-center justify-center text-muted-foreground">
                  {renderTriggerIcon(entry, spec, "h-4 w-4")}
                </span>
                <span className="truncate text-sm font-medium">
                  {entry?.name ?? spec.webhook_type ?? spec.trigger_type}
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
                  <div className="grid gap-2">
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

              {(entry?.credential_fields ?? []).map((field) => (
                <div key={field.key} className="grid gap-2 md:max-w-sm">
                  <FormLabel
                    htmlFor={`trigger-credential-${key}-${field.key}`}
                    required={lane === "channel" || !!entry?.data_extractor}
                  >
                    {field.label}
                  </FormLabel>
                  <SecretSelect
                    id={`trigger-credential-${key}-${field.key}`}
                    secrets={resources.secrets}
                    value={credentialSecretId(spec, field.key)}
                    onChange={(secretId) =>
                      patch(key, {
                        channel_credentials: {
                          ...spec.channel_credentials,
                          [field.key]: { secret_id: secretId },
                        },
                      })
                    }
                    disabled={resources.loading || secretsFailed}
                    placeholder={
                      resources.loading
                        ? tTrigger("loadingResources")
                        : tTrigger("selectSecret")
                    }
                    searchPlaceholder={tTrigger("selectSecret")}
                    emptyMessage={tTrigger("noSecrets")}
                    createLabel={tTrigger("newSecret")}
                    onCreated={resources.refresh}
                  />
                  {missing.includes(field.key) && (
                    <p role="alert" className="text-sm text-destructive">
                      {t("triggerCredentialRequired")}
                    </p>
                  )}
                </div>
              ))}
              {secretsFailed && (entry?.credential_fields ?? []).length > 0 && (
                <p role="alert" className="text-xs text-destructive">
                  {tTrigger("resourcesLoadFailed")}
                </p>
              )}

              <div className="grid gap-2">
                <FormLabel
                  htmlFor={`trigger-task-${key}`}
                  required={taskTextRequired}
                  optional={!taskTextRequired}
                >
                  {tTrigger("taskInstructions")}
                </FormLabel>
                {!taskTextRequired && (
                  <p className="text-xs text-muted-foreground">
                    {tTrigger(
                      lane === "channel"
                        ? "taskTextFromChannel"
                        : "taskTextFromCall"
                    )}
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
          <Note className="mt-2 cursor-default items-center gap-2 rounded-md border p-3 text-center text-xs text-muted-foreground/50">
            <p>{t("noTriggers")}</p>
          </Note>
        )}
      </div>
    </AccordionControl>
  );
};

export default TriggersConfig;
