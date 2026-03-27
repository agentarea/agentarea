"use client";

import { useState, useEffect, useActionState } from "react";
import { useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import {
  Clock,
  Webhook,
  Zap,
  Bot,
  Settings,
  FileJson,
  AlertTriangle,
} from "lucide-react";
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
import { useToast } from "@/hooks/use-toast";
import {
  createTriggerAction,
  updateTriggerAction,
  type TriggerFormState,
} from "./actions";

interface CreateTriggerFormProps {
  agents: any[];
  initialData?: any;
}

const WEBHOOK_TYPES = [
  "generic",
  "slack",
  "discord",
  "telegram",
  "github",
  "gmail",
  "teams",
  "linear",
  "stripe",
] as const;

// Credential fields per channel type
const CHANNEL_CREDENTIAL_FIELDS: Record<string, { key: string; label: string; placeholder: string }[]> = {
  slack: [
    { key: "signing_secret", label: "Signing Secret", placeholder: "Your Slack app's signing secret" },
  ],
  github: [
    { key: "webhook_secret", label: "Webhook Secret", placeholder: "Secret configured in GitHub webhook settings" },
  ],
  discord: [
    { key: "public_key", label: "Application Public Key", placeholder: "Your Discord application's public key" },
  ],
  linear: [
    { key: "signing_secret", label: "Signing Secret", placeholder: "Your Linear webhook signing secret" },
  ],
};

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

export function CreateTriggerForm({ agents, initialData }: CreateTriggerFormProps) {
  const { toast } = useToast();
  const router = useRouter();
  const t = useTranslations("TriggersPage.create");
  const tError = useTranslations("TriggersPage.error");
  const tSuccess = useTranslations("TriggersPage.success");

  const isEditing = !!initialData;
  const action = isEditing ? updateTriggerAction : createTriggerAction;

  const initialState: TriggerFormState = { message: "" };
  const [state, formAction, isPending] = useActionState(action, initialState);

  const [triggerType, setTriggerType] = useState<string>(
    initialData?.trigger_type || ""
  );
  const [selectedMethods, setSelectedMethods] = useState<string[]>(
    initialData?.config?.allowed_methods || ["POST"]
  );
  const [webhookType, setWebhookType] = useState<string>(
    initialData?.config?.webhook_type || "generic"
  );
  const [channelEvents, setChannelEvents] = useState<Record<string, string[]>>({});
  const [selectedEvents, setSelectedEvents] = useState<string[]>(
    initialData?.event_types || []
  );

  // Fetch channel events registry
  useEffect(() => {
    fetch("/api/proxy/v1/triggers/channels/events")
      .then((res) => res.ok ? res.json() : {})
      .then((data) => setChannelEvents(data))
      .catch(() => {});
  }, []);

  const availableEvents = channelEvents[webhookType] || [];

  const toggleEvent = (event: string) => {
    setSelectedEvents((prev) =>
      prev.includes(event)
        ? prev.filter((e) => e !== event)
        : [...prev, event]
    );
  };

  const credentialFields = CHANNEL_CREDENTIAL_FIELDS[webhookType] || [];

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

  const toggleMethod = (method: string) => {
    setSelectedMethods((prev) =>
      prev.includes(method)
        ? prev.filter((m) => m !== method)
        : [...prev, method]
    );
  };

  return (
    <form action={formAction} className="overflow-auto h-full">
      <div className="form-content lg:max-w-xl lg:mx-auto space-y-6">
        {isEditing && (
          <input type="hidden" name="id" value={initialData.id} />
        )}

        {/* Name */}
        <div className="grid gap-2">
          <FormLabel htmlFor="name" icon={Zap} required>
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

        {/* Trigger Type */}
        <div className="grid gap-2">
          <FormLabel htmlFor="trigger_type" icon={Settings} required>
            {t("triggerType")}
          </FormLabel>
          <input type="hidden" name="trigger_type" value={triggerType} />
          <Select
            value={triggerType}
            onValueChange={setTriggerType}
            disabled={isEditing}
          >
            <SelectTrigger id="trigger_type">
              <SelectValue placeholder={t("selectType")} />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="cron">
                <div className="flex items-center gap-2">
                  <Clock className="h-4 w-4" />
                  Cron
                </div>
              </SelectItem>
              <SelectItem value="webhook">
                <div className="flex items-center gap-2">
                  <Webhook className="h-4 w-4" />
                  Webhook
                </div>
              </SelectItem>
            </SelectContent>
          </Select>
          {state.errors?.trigger_type && (
            <p className="text-sm text-destructive">
              {state.errors.trigger_type[0]}
            </p>
          )}
        </div>

        {/* Agent Selector */}
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

        {/* Cron-specific config */}
        {triggerType === "cron" && (
          <>
            <div className="grid gap-2">
              <FormLabel htmlFor="cron_expression" icon={Clock} required>
                {t("cronExpression")}
              </FormLabel>
              <Input
                id="cron_expression"
                name="cron_expression"
                placeholder={t("cronPlaceholder")}
                defaultValue={initialData?.config?.cron_expression || ""}
                required
                className="font-mono"
              />
              <p className="text-xs text-muted-foreground">
                Format: minute hour day month weekday (e.g., 0 9 * * 1-5 = weekdays at 9am)
              </p>
            </div>

            <div className="grid gap-2">
              <FormLabel htmlFor="timezone" icon={Clock} required={false}>
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

        {/* Webhook-specific config */}
        {triggerType === "webhook" && (
          <>
            <div className="grid gap-2">
              <FormLabel htmlFor="webhook_type" icon={Webhook} required={false}>
                {t("webhookType")}
              </FormLabel>
              <input type="hidden" name="webhook_type" value={webhookType} />
              <Select
                value={webhookType}
                onValueChange={(v) => {
                  setWebhookType(v);
                  setSelectedEvents([]);
                }}
              >
                <SelectTrigger id="webhook_type">
                  <SelectValue placeholder={t("selectWebhookType")} />
                </SelectTrigger>
                <SelectContent>
                  {WEBHOOK_TYPES.map((type) => (
                    <SelectItem key={type} value={type}>
                      {type.charAt(0).toUpperCase() + type.slice(1)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="grid gap-2">
              <FormLabel icon={Settings} required={false}>
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

            {/* Event Type Filter */}
            {availableEvents.length > 0 && (
              <div className="grid gap-2">
                <FormLabel icon={Zap} required={false}>
                  Event Types
                </FormLabel>
                <p className="text-xs text-muted-foreground">
                  Select which events should trigger execution. Leave empty to accept all events.
                </p>
                <input type="hidden" name="event_types" value={JSON.stringify(selectedEvents)} />
                <div className="flex flex-wrap gap-2 max-h-48 overflow-y-auto rounded-md border border-input p-3">
                  {availableEvents.map((event) => (
                    <button
                      key={event}
                      type="button"
                      onClick={() => toggleEvent(event)}
                      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium transition-colors cursor-pointer ${
                        selectedEvents.includes(event)
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-muted-foreground hover:bg-muted/80"
                      }`}
                    >
                      {event}
                    </button>
                  ))}
                </div>
                {selectedEvents.length > 0 && (
                  <p className="text-xs text-muted-foreground">
                    {selectedEvents.length} event{selectedEvents.length !== 1 ? "s" : ""} selected
                  </p>
                )}
              </div>
            )}

            {/* Channel Credentials */}
            {credentialFields.length > 0 && (
              <div className="grid gap-3 rounded-md border border-input p-4">
                <div className="flex items-center gap-2">
                  <Settings className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm font-medium">Channel Credentials</span>
                  <span className="text-xs text-muted-foreground">(optional)</span>
                </div>
                <p className="text-xs text-muted-foreground">
                  Add signing credentials to verify webhook authenticity. Stored securely and never displayed.
                </p>
                {credentialFields.map((field) => (
                  <div key={field.key} className="grid gap-1.5">
                    <Label htmlFor={`cred_${field.key}`} className="text-sm">
                      {field.label}
                    </Label>
                    <Input
                      id={`cred_${field.key}`}
                      name={`credential_${field.key}`}
                      type="password"
                      placeholder={field.placeholder}
                      autoComplete="off"
                    />
                  </div>
                ))}
              </div>
            )}
          </>
        )}

        {/* Task Parameters */}
        <div className="grid gap-2">
          <FormLabel htmlFor="task_parameters" icon={FileJson} required={false}>
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
          <FormLabel
            htmlFor="failure_threshold"
            icon={AlertTriangle}
            required={false}
          >
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

        {/* Submit Button */}
        <div className="flex justify-end pt-4">
          <Button type="submit" disabled={isPending}>
            {isPending
              ? "..."
              : isEditing
                ? t("createButton").replace("Create", "Update")
                : t("createButton")}
          </Button>
        </div>

        {/* Form-level errors */}
        {state.errors?._form && (
          <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
            {state.errors._form.map((err, i) => (
              <p key={i}>{err}</p>
            ))}
          </div>
        )}
      </div>
    </form>
  );
}
