"use client";

import { useState, useEffect, useActionState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import {
  Search,
  Tag,
  Bot,
  Clock,
  Globe,
  List,
  Key,
  Code2,
  AlertTriangle,
  MessageSquare,
  Zap,
  Send,
  Hash,
  Mail,
  Webhook,
  Circle,
  Info,
  type LucideIcon,
} from "lucide-react";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
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
import FormLabel from "@/components/FormLabel/FormLabel";
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
  const [activeTab, setActiveTab] = useState("");
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
        } else {
          const firstKind = kindOrder.find((k) => data.some((e) => e.kind === k));
          if (firstKind) setActiveTab(firstKind);
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
    schedule: "Scheduling",
    messaging: "Messaging",
    event: "Events",
  };
  const kindIcons: Record<string, LucideIcon> = {
    schedule: Clock,
    messaging: MessageSquare,
    event: Zap,
  };
  const triggerIcons: Record<string, LucideIcon> = {
    cron: Clock,
    telegram: Send,
    slack: Hash,
    discord: MessageSquare,
    email: Mail,
    webhook: Webhook,
  };
  const kindOrder: CatalogEntry["kind"][] = ["schedule", "messaging", "event"];
  const kinds = new Set(catalog.map((e) => e.kind));
  const orderedKinds = kindOrder.filter((k) => kinds.has(k));

  useEffect(() => {
    if (!activeTab || isEditing) return;
    const entries = catalog.filter((e) => e.kind === activeTab);
    if (entries.length === 1) {
      setSelectedId(entries[0].id);
    }
  }, [activeTab, catalog, isEditing]);

  const renderCard = (entry: CatalogEntry) => {
    const Icon = triggerIcons[entry.icon] ?? triggerIcons[entry.id] ?? Circle;
    const isSelected = selectedId === entry.id;
    return (
      <button
        key={entry.id}
        type="button"
        onClick={() => setSelectedId(entry.id)}
        className={cn(
          "group flex items-center gap-2 rounded px-2.5 py-1.5 text-left text-[13px] transition-colors w-full",
          isSelected
            ? "bg-foreground/[0.04] text-foreground ring-1 ring-foreground/15 dark:bg-foreground/[0.06] dark:ring-foreground/20"
            : "text-muted-foreground hover:bg-muted/60 hover:text-foreground"
        )}
      >
        <Icon
          className={cn(
            "h-3.5 w-3.5 shrink-0 transition-colors",
            isSelected ? "text-foreground" : "text-muted-foreground/70"
          )}
        />
        <span className="truncate font-medium">{entry.name}</span>
      </button>
    );
  };

  return (
    <form id="create-trigger-form" action={formAction} className="overflow-auto h-full">
      <div className="form-content lg:max-w-xl lg:mx-auto space-y-5 py-5">
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
          <div className="space-y-3">
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
                <div className="grid grid-cols-2 gap-1.5">
                  {filteredEntries.map(renderCard)}
                  {filteredEntries.length === 0 && (
                    <p className="text-sm text-muted-foreground py-4 col-span-2 text-center">
                      No triggers found for &ldquo;{search}&rdquo;
                    </p>
                  )}
                </div>
              ) : (
                <Tabs value={activeTab} onValueChange={setActiveTab}>
                  <TabsList
                    className="w-full grid"
                    style={{
                      gridTemplateColumns: `repeat(${orderedKinds.length}, minmax(0, 1fr))`,
                    }}
                  >
                    {orderedKinds.map((kind) => {
                      const KindIcon = kindIcons[kind] ?? Circle;
                      return (
                        <TabsTrigger key={kind} value={kind}>
                          <KindIcon className="h-4 w-4 mr-1.5" />
                          {kindLabels[kind] ?? kind}
                        </TabsTrigger>
                      );
                    })}
                  </TabsList>
                  {orderedKinds.map((kind) => {
                    const entries = catalog.filter((e) => e.kind === kind);
                    return (
                      <TabsContent key={kind} value={kind}>
                        <div className="grid grid-cols-2 gap-1.5">
                          {entries.map(renderCard)}
                        </div>
                      </TabsContent>
                    );
                  })}
                </Tabs>
              )}
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-3">
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

        {selected && triggerType === "webhook" && (
          <div className="border-l border-border/60 pl-3 space-y-1">
            <div className="flex items-center gap-1.5">
              <Info className="h-3 w-3 text-muted-foreground shrink-0" />
              <p className="text-[12px] font-medium">Webhook endpoint</p>
            </div>
            <p className="text-[11px] leading-relaxed text-muted-foreground">
              A unique URL is generated after you create this trigger. Copy it
              from the trigger detail page and paste it into your {selected.name}{" "}
              settings.
              {selected.webhook_type === "telegram" &&
                " Use /setwebhook with @BotFather or the Telegram Bot API."}
              {selected.webhook_type === "slack" &&
                " In Slack → Event Subscriptions, paste under Request URL."}
              {selected.webhook_type === "discord" &&
                " In Discord → General Information, paste under Interactions Endpoint URL."}
              {selected.webhook_type === "gmail" &&
                " Set up a Google Cloud Pub/Sub push subscription pointing to this URL."}
              {selected.webhook_type === "generic" &&
                " Send HTTP requests to this URL from any service or script."}
            </p>
          </div>
        )}

        {/* Name */}
        <div className="grid gap-2">
          <FormLabel htmlFor="name" icon={Tag} required>
            {t("name")}
          </FormLabel>
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

        {/* Agent */}
        <div className="grid gap-2">
          <FormLabel htmlFor="agent_id" icon={Bot} required>
            {t("agent")}
          </FormLabel>
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

        {/* Cron config */}
        {triggerType === "cron" && (
          <>
            <div className="grid gap-2">
              <CronScheduler
                name="cron_expression"
                defaultValue={initialData?.config?.cron_expression || selected?.default_cron || ""}
              />
            </div>

            <div className="grid gap-2">
              <FormLabel htmlFor="timezone" icon={Clock}>
                {t("timezone")}
              </FormLabel>
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
          </>
        )}

        {/* Webhook config */}
        {triggerType === "webhook" && (
          <>
            <div className="grid gap-2">
              <FormLabel icon={Globe}>
                {t("allowedMethods")}
              </FormLabel>
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
              <div className="grid gap-2">
                <FormLabel icon={List}>
                  Event Types
                </FormLabel>
                <p className="text-xs text-muted-foreground">
                  Select which events trigger execution. Leave empty to accept all.
                </p>
                <input
                  type="hidden"
                  name="event_types"
                  value={JSON.stringify(selectedEvents)}
                />
                <div className="flex flex-wrap gap-1.5 max-h-48 overflow-y-auto">
                  {availableEvents.map((event) => {
                    const isSel = selectedEvents.includes(event);
                    return (
                      <button
                        key={event}
                        type="button"
                        onClick={() => toggleEvent(event)}
                        className={cn(
                          "inline-flex items-center rounded px-2 py-0.5 text-[11px] font-medium transition-colors",
                          isSel
                            ? "bg-foreground text-background"
                            : "bg-muted/60 text-muted-foreground hover:bg-muted hover:text-foreground"
                        )}
                      >
                        {event}
                      </button>
                    );
                  })}
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

        {/* Credentials */}
        {credentialFields.length > 0 && (
          <>
            <p className="text-xs text-muted-foreground">
              {selected?.data_extractor
                ? "Required to connect to the service."
                : "Add signing credentials to verify webhook authenticity. Stored securely."}
            </p>
            {credentialFields.map((field) => (
              <div key={field.key} className="grid gap-2">
                <FormLabel
                  htmlFor={`cred_${field.key}`}
                  icon={Key}
                  required={!!selected?.data_extractor}
                >
                  {field.label}
                </FormLabel>
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
          </>
        )}

        {/* Task Parameters */}
        <div className="grid gap-2">
          <FormLabel htmlFor="task_parameters" icon={Code2} optional>
            {t("taskParameters")}
          </FormLabel>
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

        {/* Failure Threshold */}
        <div className="grid gap-2">
          <FormLabel htmlFor="failure_threshold" icon={AlertTriangle} optional>
            {t("failureThreshold")}
          </FormLabel>
          <Input
            id="failure_threshold"
            name="failure_threshold"
            type="number"
            min={1}
            placeholder={t("failureThresholdPlaceholder")}
            defaultValue={initialData?.failure_threshold || ""}
          />
        </div>

        {state.errors?._form && (
          <div className="border-l-2 border-destructive bg-destructive/5 px-3 py-2 text-[12px] text-destructive">
            {state.errors._form.map((err, i) => (
              <p key={i}>{err}</p>
            ))}
          </div>
        )}

        {/* Submit */}
        <div className="flex items-center justify-end gap-2 border-t border-border/50 pt-4">
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => router.push("/triggers")}
            className="h-8 text-[13px] text-muted-foreground hover:text-foreground"
          >
            Cancel
          </Button>
          <Button
            type="submit"
            size="sm"
            disabled={isPending || !selected}
            className="h-8 text-[13px]"
          >
            {isPending
              ? "..."
              : isEditing
                ? t("createButton").replace("Create", "Update")
                : t("createButton")}
          </Button>
        </div>
      </div>
    </form>
  );
}
