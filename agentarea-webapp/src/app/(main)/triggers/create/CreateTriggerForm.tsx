"use client";

import { useState, useEffect, useActionState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { Search } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";
import { cn } from "@/lib/utils";
import { useToast } from "@/hooks/use-toast";
import {
  createTriggerAction,
  updateTriggerAction,
  type TriggerFormState,
} from "./actions";
import { CronScheduler } from "./CronScheduler";

interface CatalogEntry {
  id: string;
  name: string;
  icon: string;
  description: string;
  kind: "messaging" | "event" | "schedule";
  backend_type: "cron" | "webhook";
  webhook_type?: string;
  default_methods?: string[];
  default_cron?: string;
  data_extractor?: string;
  credential_fields?: { key: string; label: string; placeholder: string }[];
  events?: string[];
}

interface CreateTriggerFormProps {
  agents: any[];
  initialData?: any;
}

const HTTP_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"] as const;

const TIMEZONES = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Asia/Kolkata",
  "Australia/Sydney",
  "Pacific/Auckland",
] as const;

function resolveInitialId(catalog: CatalogEntry[], initialData?: any): string {
  if (!initialData) return "";
  if (initialData.trigger_type === "cron") return "cron";
  const wt = initialData.config?.webhook_type;
  if (!wt) return "webhook";
  return catalog.find((e) => e.webhook_type === wt)?.id ?? "webhook";
}

export function CreateTriggerForm({
  agents,
  initialData,
}: CreateTriggerFormProps) {
  const { toast } = useToast();
  const router = useRouter();
  const t = useTranslations("TriggersPage.create");
  const tError = useTranslations("TriggersPage.error");
  const tSuccess = useTranslations("TriggersPage.success");

  const isEditing = !!initialData;
  const action = isEditing ? updateTriggerAction : createTriggerAction;

  const initialState: TriggerFormState = { message: "" };
  const [state, formAction, isPending] = useActionState(action, initialState);

  const [catalog, setCatalog] = useState<CatalogEntry[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [search, setSearch] = useState("");
  const [selectedMethods, setSelectedMethods] = useState<string[]>(
    initialData?.config?.allowed_methods || ["POST"]
  );
  const [selectedEvents, setSelectedEvents] = useState<string[]>(
    initialData?.event_types || []
  );

  // Fetch catalog from backend
  useEffect(() => {
    fetch("/api/proxy/v1/triggers/catalog")
      .then((res) => (res.ok ? res.json() : []))
      .then((data: CatalogEntry[]) => {
        setCatalog(data);
        if (initialData) {
          setSelectedId(resolveInitialId(data, initialData));
        }
      })
      .catch(() => {});
  }, []);

  const selected = catalog.find((e) => e.id === selectedId);
  const triggerType = selected?.backend_type ?? "";
  const webhookType = selected?.webhook_type ?? "";

  // Reset methods and events when selection changes
  useEffect(() => {
    if (selected && !isEditing) {
      setSelectedMethods(selected.default_methods ?? ["POST"]);
      setSelectedEvents([]);
    }
  }, [selectedId]);

  const availableEvents = selected?.events ?? [];
  const credentialFields = selected?.credential_fields ?? [];

  const toggleEvent = (event: string) => {
    setSelectedEvents((prev) =>
      prev.includes(event) ? prev.filter((e) => e !== event) : [...prev, event]
    );
  };

  const toggleMethod = (method: string) => {
    setSelectedMethods((prev) =>
      prev.includes(method)
        ? prev.filter((m) => m !== method)
        : [...prev, method]
    );
  };

  useEffect(() => {
    if (state.success) {
      toast({
        title: isEditing ? tSuccess("updated") : tSuccess("created"),
        variant: "success",
      });
      router.push("/triggers");
      router.refresh();
    } else if (state.errors) {
      toast({
        title: isEditing ? tError("updateFailed") : tError("createFailed"),
        description: state.message,
        variant: "destructive",
      });
    }
  }, [state, toast, router, isEditing, tSuccess, tError]);

  // Filter catalog by search
  const filteredEntries = search.trim()
    ? catalog.filter(
        (e) =>
          e.name.toLowerCase().includes(search.toLowerCase()) ||
          e.description.toLowerCase().includes(search.toLowerCase())
      )
    : null;

  // Group by kind for default view
  const kindLabels: Record<string, string> = {
    messaging: "Messaging",
    schedule: "Scheduling",
    event: "Events",
  };
  const kinds = [...new Set(catalog.map((e) => e.kind))];

  const renderCard = (entry: CatalogEntry) => (
    <button
      key={entry.id}
      type="button"
      onClick={() => setSelectedId(entry.id)}
      title={entry.description}
      className={cn(
        "flex flex-col items-center gap-1 rounded-lg border p-2 text-center transition-colors w-[72px] shrink-0",
        selectedId === entry.id
          ? "border-primary bg-primary/10 text-primary"
          : "border-border bg-card hover:border-primary/50 hover:bg-muted/50"
      )}
    >
      <span className="text-[10px] leading-tight font-medium line-clamp-2">
        {entry.name}
      </span>
    </button>
  );

  return (
    <form action={formAction} className="overflow-auto h-full">
      <div className="mx-auto w-full max-w-3xl space-y-6 px-4 py-5">
        {isEditing && (
          <input type="hidden" name="id" value={initialData.id} />
        )}
        <input type="hidden" name="trigger_type" value={triggerType} />
        {triggerType === "webhook" && (
          <input type="hidden" name="webhook_type" value={webhookType} />
        )}
        {selected?.data_extractor && (
          <input type="hidden" name="data_extractor" value={selected.data_extractor} />
        )}

        {/* Catalog Picker */}
        {!isEditing ? (
          <div className="space-y-3 rounded-lg border border-border/60 bg-muted/20 p-4 dark:bg-zinc-900/40">
            <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              {t("triggerType")}
            </div>
            <div className="relative">
              <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-muted-foreground" />
              <Input
                type="text"
                placeholder="Search triggers..."
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                className="pl-8"
              />
            </div>
            <div className="max-h-72 overflow-y-auto">
              {filteredEntries ? (
                <div className="flex flex-wrap gap-2">
                  {filteredEntries.map(renderCard)}
                  {filteredEntries.length === 0 && (
                    <p className="text-sm text-muted-foreground py-4 w-full text-center">
                      No triggers found for &ldquo;{search}&rdquo;
                    </p>
                  )}
                </div>
              ) : (
                <div className="space-y-4">
                  {kinds.map((kind) => {
                    const entries = catalog.filter((e) => e.kind === kind);
                    return (
                      <div key={kind}>
                        <p className="text-xs font-semibold text-muted-foreground uppercase tracking-wide mb-2">
                          {kindLabels[kind] ?? kind}
                        </p>
                        <div className="flex flex-wrap gap-2">
                          {entries.map(renderCard)}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
            {selected && (
              <p className="text-xs text-muted-foreground">
                <span className="font-medium text-foreground">
                  {selected.name}
                </span>{" "}
                &mdash; {selected.description}
              </p>
            )}
          </div>
        ) : (
          <div className="flex items-center gap-3 rounded-lg border border-border/60 bg-muted/20 p-4 dark:bg-zinc-900/40">
            {selected && (
              <span className="text-lg">{selected.icon}</span>
            )}
            <div>
              <p className="text-sm font-medium">
                {selected?.name ?? initialData.trigger_type}
              </p>
              <p className="text-xs text-muted-foreground">
                {selected?.description}
              </p>
            </div>
          </div>
        )}

        {/* Basic Info */}
        <div className="space-y-4 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Basic Info
          </div>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="name" className="text-sm">
                {t("name")} <span className="text-red-500">*</span>
              </Label>
              <Input
                id="name"
                name="name"
                placeholder={t("namePlaceholder")}
                defaultValue={initialData?.name || ""}
                required
              />
              {state.errors?.name && (
                <p className="text-sm text-destructive">{state.errors.name[0]}</p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="agent_id" className="text-sm">
                {t("agent")} <span className="text-red-500">*</span>
              </Label>
              <Select
                name="agent_id"
                defaultValue={initialData?.agent_id || ""}
              >
                <SelectTrigger id="agent_id">
                  <SelectValue placeholder={t("selectAgent")} />
                </SelectTrigger>
                <SelectContent>
                  {agents.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      {agent.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
              {state.errors?.agent_id && (
                <p className="text-sm text-destructive">
                  {state.errors.agent_id[0]}
                </p>
              )}
            </div>
          </div>
        </div>

        {/* Cron config */}
        {triggerType === "cron" && (
          <div className="space-y-4 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
            <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Schedule
            </div>
            <CronScheduler
              name="cron_expression"
              defaultValue={initialData?.config?.cron_expression || selected?.default_cron || ""}
            />
            <div className="space-y-1.5">
              <Label htmlFor="timezone" className="text-sm">
                {t("timezone")}
              </Label>
              <Select
                name="timezone"
                defaultValue={initialData?.config?.timezone || "UTC"}
              >
                <SelectTrigger id="timezone">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {TIMEZONES.map((tz) => (
                    <SelectItem key={tz} value={tz}>
                      {tz}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        )}

        {/* Webhook config */}
        {triggerType === "webhook" && (
          <>
            <div className="space-y-4 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
              <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                {t("allowedMethods")}
              </div>
              <div className="flex flex-wrap gap-3">
                {HTTP_METHODS.map((method) => (
                  <div key={method} className="flex items-center gap-2">
                    <Checkbox
                      id={`method_${method}`}
                      name={`method_${method}`}
                      checked={selectedMethods.includes(method)}
                      onCheckedChange={() => toggleMethod(method)}
                    />
                    <Label
                      htmlFor={`method_${method}`}
                      className="text-sm font-mono cursor-pointer"
                    >
                      {method}
                    </Label>
                  </div>
                ))}
              </div>
            </div>

            {availableEvents.length > 0 && (
              <div className="space-y-3 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
                <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
                  Event Types
                </div>
                <p className="text-xs text-muted-foreground">
                  Select which events trigger execution. Leave empty to accept
                  all.
                </p>
                <input
                  type="hidden"
                  name="event_types"
                  value={JSON.stringify(selectedEvents)}
                />
                <div className="flex flex-wrap gap-2 max-h-48 overflow-y-auto">
                  {availableEvents.map((event) => (
                    <button
                      key={event}
                      type="button"
                      onClick={() => toggleEvent(event)}
                      className={cn(
                        "inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors cursor-pointer",
                        selectedEvents.includes(event)
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-muted-foreground hover:bg-muted/80"
                      )}
                    >
                      {event}
                    </button>
                  ))}
                </div>
                {selectedEvents.length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    {selectedEvents.length} event
                    {selectedEvents.length !== 1 ? "s" : ""} selected
                  </p>
                )}
              </div>
            )}

          </>
        )}

        {/* Channel Credentials — shown for any trigger with credential_fields */}
        {credentialFields.length > 0 && (
          <div className="space-y-3 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
            <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
              Credentials
            </div>
            <p className="text-xs text-muted-foreground">
              {selected?.data_extractor
                ? "Required to connect to the service."
                : "Add signing credentials to verify webhook authenticity. Stored securely."}
            </p>
            {credentialFields.map((field) => (
              <div key={field.key} className="space-y-1.5">
                <Label
                  htmlFor={`cred_${field.key}`}
                  className="text-sm"
                >
                  {field.label}
                  {selected?.data_extractor && <span className="text-red-500"> *</span>}
                </Label>
                <Input
                  id={`cred_${field.key}`}
                  name={`credential_${field.key}`}
                  type="password"
                  placeholder={field.placeholder}
                  autoComplete="off"
                  required={!!selected?.data_extractor}
                />
              </div>
            ))}
          </div>
        )}

        {/* Advanced */}
        <div className="space-y-4 rounded-lg border border-border/60 bg-background p-4 dark:bg-zinc-900/30">
          <div className="text-[11px] font-medium uppercase tracking-wide text-muted-foreground">
            Advanced
          </div>
          <div className="space-y-3">
            <div className="space-y-1.5">
              <Label htmlFor="task_parameters" className="text-sm">
                {t("taskParameters")}
              </Label>
              <Textarea
                id="task_parameters"
                name="task_parameters"
                placeholder={t("taskParametersPlaceholder")}
                defaultValue={
                  initialData?.task_parameters
                    ? JSON.stringify(initialData.task_parameters, null, 2)
                    : ""
                }
                className="font-mono min-h-[100px]"
              />
              {state.errors?.task_parameters && (
                <p className="text-sm text-destructive">
                  {state.errors.task_parameters[0]}
                </p>
              )}
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="failure_threshold" className="text-sm">
                {t("failureThreshold")}
              </Label>
              <Input
                id="failure_threshold"
                name="failure_threshold"
                type="number"
                min={1}
                placeholder={t("failureThresholdPlaceholder")}
                defaultValue={initialData?.failure_threshold || ""}
              />
            </div>
          </div>
        </div>

        {/* Submit */}
        <div className="flex justify-end">
          <Button type="submit" disabled={isPending || !selected}>
            {isPending
              ? "..."
              : isEditing
                ? t("createButton").replace("Create", "Update")
                : t("createButton")}
          </Button>
        </div>

        {state.errors?._form && (
          <div className="rounded-lg bg-destructive/10 p-3 text-sm text-destructive">
            {state.errors._form.map((err, i) => (
              <p key={i}>{err}</p>
            ))}
          </div>
        )}
      </div>
    </form>
  );
}
