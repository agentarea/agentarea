"use client";

import { useActionState, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  AlertTriangle,
  ArrowLeftRight,
  CalendarClock,
  ChevronDown,
  FileText,
  Globe,
  KeyRound,
  MessageSquare,
  Paperclip,
  SlidersHorizontal,
  Tag,
  Webhook,
} from "lucide-react";
import type { AgentResponse, TriggerResponse } from "@/api/client/types.gen";
import { AgentSelect } from "@/components/AgentSelect";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import { FilePickerPanel } from "@/components/ResourcePicker/FilePickerPanel";
import { SecretSelect } from "@/components/SecretSelect";
import SectionLoadError from "@/components/SectionLoadError";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import Divider from "@/components/ui/divider";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Textarea } from "@/components/ui/textarea";
import { useAttachableResources } from "@/hooks/use-attachable-resources";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import {
  composeTaskParameters,
  normalizeTaskParameters,
  type TaskParameterRef,
} from "../components/taskParameters";
import { SigningSecretIssuedDialog } from "../components/WebhookSigning";
import {
  createTriggerAction,
  updateTriggerAction,
  type TriggerCatalogEntry,
  type TriggerFormState,
} from "./actions";
import { CronScheduler } from "./CronScheduler";
import type { StreamOptions } from "./streamOptions";
import { TIMEZONES } from "./timezones";
import { TriggerExecutionContext } from "./TriggerExecutionContext";
import { triggerShape } from "./triggerShape";

interface CreateTriggerFormProps {
  agents: AgentResponse[];
  /** `null` when the trigger catalog could not be loaded. */
  catalog: TriggerCatalogEntry[] | null;
  streams: StreamOptions;
  initialData?: TriggerResponse;
}

const HTTP_METHODS = [
  "GET",
  "POST",
  "PUT",
  "PATCH",
  "DELETE",
  "HEAD",
  "OPTIONS",
] as const;
const INLINE_ERROR_FIELDS = new Set([
  "name",
  "trigger_type",
  "task_parameters",
  "cron_expression",
  "description",
  "agent_id",
  "stream_id",
  "failure_threshold",
  "allowed_methods",
]);
const KIND_ORDER: TriggerCatalogEntry["kind"][] = [
  "schedule",
  "messaging",
  "event",
];

type SelectableResource = TaskParameterRef;

const TYPE_GRID = "grid gap-2 sm:grid-cols-2 xl:grid-cols-3";

function resolveInitialId(
  catalog: TriggerCatalogEntry[],
  initialData?: TriggerResponse
): string {
  if (!initialData) return "";
  if (initialData.trigger_type === "cron") {
    return (
      catalog.find(
        (entry) =>
          entry.backend_type === "cron" &&
          (entry.data_extractor ?? null) ===
            (initialData.data_extractor ?? null)
      )?.id ?? "cron"
    );
  }
  if (initialData.trigger_type === "stream") return "stream";
  const wt = initialData.webhook_type;
  if (!wt) return "webhook";
  return catalog.find((e) => e.webhook_type === wt)?.id ?? "webhook";
}

export function CreateTriggerForm({
  agents,
  catalog: loadedCatalog,
  streams,
  initialData,
}: CreateTriggerFormProps) {
  const router = useWorkspaceRouter();
  const t = useTranslations("TriggersPage.create");
  const tFilter = useTranslations("TriggersPage.filter");
  const tError = useTranslations("TriggersPage.error");

  const isEditing = !!initialData;
  const action = isEditing ? updateTriggerAction : createTriggerAction;

  const initialState: TriggerFormState = { message: "" };
  const [state, formAction, isPending] = useActionState(action, initialState);

  // A failed load used to leave an empty type dropdown that looked like the
  // product simply had no trigger types, so the failure is said out loud.
  const catalogFailed = loadedCatalog === null;
  const catalog = useMemo(() => loadedCatalog ?? [], [loadedCatalog]);
  const [selectedId, setSelectedId] = useState(() =>
    resolveInitialId(catalog, initialData)
  );
  // A new trigger starts with a name, as a new agent or model does: generic
  // until a type is picked, then named after the type. Once someone types
  // their own, picking another type leaves it alone.
  const [name, setName] = useState(
    () => initialData?.name ?? t("automationNamePlaceholder")
  );
  const [nameEdited, setNameEdited] = useState(isEditing);
  const [selectedAgentId, setSelectedAgentId] = useState(
    initialData?.agent_id ?? ""
  );
  const [credentialSecrets, setCredentialSecrets] = useState<
    Record<string, string>
  >({});
  // Picking a type collapses the grid to the one picked; "Change" reopens it.
  const [changingType, setChangingType] = useState(false);
  const [runSettingsOpen, setRunSettingsOpen] = useState(false);

  useEffect(() => {
    if (
      state.errors?.failure_threshold ||
      state.errors?.allowed_methods ||
      state.errors?.description
    )
      setRunSettingsOpen(true);
  }, [state.errors]);
  // Field errors the form has no inline slot for (e.g. `config.*` from the
  // schema) are listed in the banner with their path, not dropped.
  const unplacedErrors = Object.entries(state.errors ?? {}).filter(
    ([key]) =>
      key !== "_form" &&
      !INLINE_ERROR_FIELDS.has(key) &&
      !key.startsWith("credential_secret_")
  );
  const [typeMissing, setTypeMissing] = useState(false);
  const [agentMissing, setAgentMissing] = useState(false);
  const [selectedMethods, setSelectedMethods] = useState<string[]>(
    initialData?.allowed_methods ?? ["POST"]
  );
  const [selectedEvents, setSelectedEvents] = useState<string[]>(
    initialData?.event_types || []
  );
  const initialTaskParameters = useMemo(
    () => normalizeTaskParameters(initialData?.task_parameters),
    [initialData?.task_parameters]
  );
  const [taskText, setTaskText] = useState(initialTaskParameters.text);
  const [taskFiles, setTaskFiles] = useState(initialTaskParameters.files);
  const [taskSkills, setTaskSkills] = useState<TaskParameterRef[]>(
    initialTaskParameters.skills
  );
  const [taskMcps, setTaskMcps] = useState<TaskParameterRef[]>(
    initialTaskParameters.mcps
  );
  const resources = useAttachableResources({
    withFiles: true,
    withSecrets: true,
  });
  const {
    mcpInstances: availableMcps,
    files: availableFiles,
    secrets: availableSecrets,
    loading: resourcesLoading,
    failed: resourceErrors,
  } = resources;
  const availableSkills = useMemo<SelectableResource[]>(
    () =>
      resources.skills.map((skill) => ({
        id: skill.id,
        name: skill.name,
        description: skill.description,
      })),
    [resources.skills]
  );

  const selected = catalog.find((e) => e.id === selectedId);
  const webhookType = initialData?.webhook_type ?? selected?.webhook_type ?? "";
  const { triggerType, isChannel, taskTextRequired } = triggerShape({
    selected,
    initialData,
  });
  const timezones = Array.from(
    new Set([
      ...TIMEZONES,
      ...(initialData?.timezone ? [initialData.timezone] : []),
    ])
  );

  // Reset methods and events when selection changes
  useEffect(() => {
    if (selected && !isEditing) {
      setSelectedMethods(selected.default_methods ?? ["POST"]);
      setSelectedEvents([]);
    }
  }, [isEditing, selected]);

  const availableEvents = Array.from(
    new Set([...(selected?.events ?? []), ...(initialData?.event_types ?? [])])
  );
  const credentialFields = selected?.credential_fields ?? [];
  const credentialsRequired =
    !!selected?.data_extractor && !initialData?.has_channel_credentials;
  const showEvents =
    triggerType === "webhook" && !isChannel && availableEvents.length > 0;

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

  const taskParametersValue = useMemo(
    () =>
      JSON.stringify(
        composeTaskParameters({
          text: taskText,
          files: taskFiles,
          skills: taskSkills,
          mcps: taskMcps,
          rest: initialTaskParameters.rest,
        })
      ),
    [taskText, taskFiles, taskSkills, taskMcps, initialTaskParameters.rest]
  );

  // Mirror pending state onto the form element so the header controls can
  // render the submit button's loading state (see useFormSubmittingState).
  useEffect(() => {
    const form = document.getElementById("create-trigger-form");
    if (!form) return;
    form.setAttribute("data-submitting", String(isPending));
    form.dispatchEvent(
      new CustomEvent("form-submitting", {
        detail: { isSubmitting: isPending },
      })
    );
  }, [isPending]);

  useEffect(() => {
    // A generated signing secret is shown first: navigating away would lose it.
    if (state.success && !state.signing) {
      // The action revalidated both paths, so the destination renders fresh.
      // A `router.refresh()` here cancels this navigation instead.
      router.push(initialData ? `/triggers/${initialData.id}` : "/triggers");
    }
  }, [state, router, initialData]);

  // Kind is only a grouping header inside the type picker.
  const kindLabels: Record<TriggerCatalogEntry["kind"], string> = {
    schedule: tFilter("schedules"),
    messaging: tFilter("channels"),
    event: tFilter("events"),
  };
  const showTypePicker = !isEditing && (!selected || changingType);
  const kinds = new Set(catalog.map((e) => e.kind));
  const orderedKinds = KIND_ORDER.filter((k) => kinds.has(k));

  // A new trigger cannot be saved without a type or an agent; both are
  // checked here, before the post, rather than left to the server's 422.
  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    if (isEditing) return;
    if (!selectedAgentId) {
      setAgentMissing(true);
      document.getElementById("agent_id")?.focus();
    }
    // Scrolled to after the agent's focus: on a phone both share one scroll,
    // and the type is the field further up.
    if (!selected) {
      setTypeMissing(true);
      document
        .getElementById("trigger-type-field")
        ?.scrollIntoView({ block: "start", behavior: "smooth" });
    }
    if (!selected || !selectedAgentId) event.preventDefault();
  };

  const fileControl = (
    <Sheet>
      <SheetTrigger asChild>
        <Button
          id="task_files"
          type="button"
          variant="ghost"
          size="xs"
          className="text-muted-foreground"
        >
          <Paperclip />
          {t("taskFilesPlaceholder")}
        </Button>
      </SheetTrigger>
      {/* Sized like the task composer's attach sheet, which it mirrors. */}
      <SheetContent className="flex flex-col gap-0 overflow-hidden p-0 sm:w-[420px] sm:max-w-[420px]">
        <FilePickerPanel
          title={t("taskFiles")}
          description={t("taskFilesHint")}
          files={availableFiles}
          selected={taskFiles}
          onChange={setTaskFiles}
          loading={resourcesLoading}
          failed={resourceErrors.includes("files")}
          onRefresh={resources.refresh}
        />
      </SheetContent>
    </Sheet>
  );
  return (
    <>
      {state.success && state.signing && (
        <SigningSecretIssuedDialog
          title={t("createdWithSecretTitle")}
          secret={state.signing.secret}
          scheme={state.signing.scheme}
          onDone={() =>
            router.push(
              state.triggerId ? `/triggers/${state.triggerId}` : "/triggers"
            )
          }
        />
      )}
      <form
        id="create-trigger-form"
        action={formAction}
        onSubmit={handleSubmit}
        onInvalidCapture={(event) => {
          if (
            (event.target as HTMLElement).closest("details[data-run-settings]")
          )
            setRunSettingsOpen(true);
        }}
        className="flex h-full flex-col overflow-auto lg:flex-row lg:overflow-hidden"
      >
        {isEditing && <input type="hidden" name="id" value={initialData.id} />}
        <input type="hidden" name="trigger_type" value={triggerType} />
        {triggerType === "webhook" && (
          <input type="hidden" name="webhook_type" value={webhookType} />
        )}
        {selected?.data_extractor && (
          <input
            type="hidden"
            name="data_extractor"
            value={selected.data_extractor}
          />
        )}
        <input
          type="hidden"
          name="task_parameters"
          value={taskParametersValue}
        />
        {triggerType === "webhook" && (
          <input
            type="hidden"
            name="event_types"
            value={JSON.stringify(selectedEvents)}
          />
        )}
        {/* A channel shows no method checkboxes, and the update action reads the
          methods straight off them with no fallback — carrying them hidden is
          what keeps an edit from saving an empty allowed_methods. */}
        {triggerType === "webhook" &&
          isChannel &&
          selectedMethods.map((method) => (
            <input
              key={method}
              type="hidden"
              name={`method_${method}`}
              value="on"
            />
          ))}
        <div className="min-w-0 flex-1 px-4 py-5 lg:overflow-auto">
          <div className="form-content mx-auto w-full max-w-4xl pb-5">
            {state.errors && (
              <FormError>
                {state.errors._form
                  ? state.errors._form.join(" ")
                  : `${isEditing ? tError("updateFailed") : tError("createFailed")}${
                      state.message ? `: ${state.message}` : ""
                    }`}
                {/* Field errors the form has no inline slot for (e.g.
                  `config.*` from the schema) are listed with their path, not
                  dropped. */}
                {unplacedErrors.map(([path, messages]) => (
                  <span key={path} className="block">
                    <span className="font-mono">{path}</span>:{" "}
                    {messages.join(", ")}
                  </span>
                ))}
              </FormError>
            )}

            <div className="space-y-2">
              <FormLabel htmlFor="name" icon={Tag} required>
                {t("automationName")}
              </FormLabel>
              <Input
                id="name"
                name="name"
                placeholder={t("automationNamePlaceholder")}
                value={name}
                onChange={(event) => {
                  setName(event.target.value);
                  setNameEdited(true);
                }}
                // A suggested name is meant to be typed over, not edited.
                onFocus={(event) => {
                  if (!nameEdited) event.currentTarget.select();
                }}
                required
              />
              {state.errors?.name && (
                <p className="form-error">{state.errors.name[0]}</p>
              )}
            </div>

            <div className="space-y-2">
              {/* Until a type is picked neither answer is true yet, so the
                label stays bare rather than claiming the text is optional. */}
              <FormLabel
                htmlFor="task_text"
                icon={MessageSquare}
                required={taskTextRequired}
                optional={Boolean(triggerType) && !taskTextRequired}
              >
                {t("taskInstructions")}
              </FormLabel>
              {Boolean(triggerType) && !taskTextRequired && (
                <p className="note">
                  {t(
                    triggerType === "stream"
                      ? "taskTextFromStream"
                      : isChannel
                        ? "taskTextFromChannel"
                        : "taskTextFromCall"
                  )}
                </p>
              )}
              <Textarea
                id="task_text"
                value={taskText}
                onChange={(event) => setTaskText(event.target.value)}
                placeholder={t("taskTextPlaceholder")}
                className="h-[200px] resize-none"
                required={taskTextRequired}
              />
              {state.errors?.task_parameters && (
                <p className="form-error">{state.errors.task_parameters[0]}</p>
              )}
            </div>

            <Divider />

            <div id="trigger-type-field" className="scroll-mt-5 space-y-2">
              <div className="flex items-center justify-between gap-2">
                <FormLabel icon={ENTITY_ICONS.trigger} required={!isEditing}>
                  {t("triggerType")}
                </FormLabel>
                {!isEditing && selected && !changingType && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="xs"
                    className="text-muted-foreground"
                    onClick={() => setChangingType(true)}
                  >
                    {t("changeType")}
                  </Button>
                )}
              </div>
              {(typeMissing || state.errors?.trigger_type) && (
                <p role="alert" className="form-error">
                  {state.errors?.trigger_type?.[0] ?? t("selectType")}
                </p>
              )}
              {catalogFailed && (
                <p role="alert" className="form-error">
                  {t("catalogLoadFailed")}
                </p>
              )}
              {showTypePicker ? (
                <div
                  role="group"
                  aria-label={t("triggerType")}
                  className="space-y-3"
                >
                  {orderedKinds.map((kind) => (
                    <div key={kind} className="space-y-1.5">
                      <p className="note">{kindLabels[kind]}</p>
                      <div className={TYPE_GRID}>
                        {catalog
                          .filter((entry) => entry.kind === kind)
                          .map((entry) => (
                            <LinkedCard
                              key={entry.id}
                              compact
                              hideHoverLink
                              // The catalog owns the artwork, as on the
                              // trigger cards: drawing it from a map here is
                              // how channels the map never heard of ended up
                              // as dots.
                              icon={entry.icon_url ?? ENTITY_ICONS.trigger}
                              title={entry.name}
                              subtitle={
                                <span
                                  className="truncate text-xs"
                                  title={entry.description}
                                >
                                  {entry.description}
                                </span>
                              }
                              selected={entry.id === selectedId}
                              onClick={() => {
                                setSelectedId(entry.id);
                                if (!nameEdited)
                                  setName(
                                    t("suggestedName", { type: entry.name })
                                  );
                                setChangingType(false);
                                setTypeMissing(false);
                              }}
                            />
                          ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <div className="space-y-1.5">
                  {/* The chosen card keeps the group it was picked from. */}
                  {selected && (
                    <p className="note">{kindLabels[selected.kind]}</p>
                  )}
                  <div className={TYPE_GRID}>
                    {/* Same grid as the picker: the chosen card keeps its
                      cell's width. */}
                    <LinkedCard
                      compact
                      hideHoverLink
                      icon={selected?.icon_url ?? ENTITY_ICONS.trigger}
                      title={selected?.name ?? initialData?.trigger_type ?? ""}
                      subtitle={
                        selected?.description && (
                          <span className="truncate text-xs">
                            {selected.description}
                          </span>
                        )
                      }
                      // An edit cannot change the type: shown, not offered.
                      onClick={
                        isEditing ? undefined : () => setChangingType(true)
                      }
                      className={
                        isEditing
                          ? "cursor-default hover:translate-y-0 hover:shadow-none active:scale-100"
                          : undefined
                      }
                    />
                  </div>
                </div>
              )}
            </div>

            {!showTypePicker && triggerType === "stream" && (
              <div className="space-y-2 md:max-w-sm">
                <FormLabel
                  htmlFor="stream_id"
                  icon={ENTITY_ICONS.stream}
                  required
                >
                  {t("stream")}
                </FormLabel>
                {/* The binding is fixed once saved: an update cannot move a
                  trigger to another stream. */}
                <Select
                  name="stream_id"
                  defaultValue={initialData?.stream_id ?? undefined}
                  disabled={isEditing || streams.error !== null}
                  required
                >
                  <SelectTrigger id="stream_id">
                    <SelectValue
                      placeholder={
                        streams.error === null && streams.items.length === 0
                          ? t("noStreams")
                          : undefined
                      }
                    />
                  </SelectTrigger>
                  <SelectContent>
                    {streams.items.map((stream) => (
                      <SelectItem key={stream.id} value={stream.id}>
                        {stream.name}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                {streams.error && <SectionLoadError message={streams.error} />}
                <p className="note">{t("streamHint")}</p>
                {state.errors?.stream_id && (
                  <p className="form-error">{state.errors.stream_id[0]}</p>
                )}
              </div>
            )}

            {!showTypePicker && triggerType === "cron" && (
              <>
                <div className="grid grid-cols-[minmax(0,1fr)] gap-2">
                  <FormLabel icon={CalendarClock} required>
                    {t("schedule")}
                  </FormLabel>
                  <CronScheduler
                    name="cron_expression"
                    defaultValue={
                      initialData?.cron_expression ??
                      selected?.default_cron ??
                      ""
                    }
                  />
                  {state.errors?.cron_expression && (
                    <p className="form-error">
                      {state.errors.cron_expression[0]}
                    </p>
                  )}
                </div>
                <div className="space-y-2 md:max-w-sm">
                  <FormLabel htmlFor="timezone" icon={Globe}>
                    {t("timezone")}
                  </FormLabel>
                  <Select
                    name="timezone"
                    defaultValue={initialData?.timezone ?? "UTC"}
                  >
                    <SelectTrigger id="timezone">
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {timezones.map((tz) => (
                        <SelectItem key={tz} value={tz}>
                          {tz}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </>
            )}

            {!showTypePicker && credentialFields.length > 0 && (
              <div className="space-y-2">
                <div className="grid gap-5 sm:grid-cols-2">
                  {credentialFields.map((field) => (
                    <div
                      key={`${selectedId}:${field.key}`}
                      className="grid content-start gap-2"
                    >
                      <FormLabel
                        htmlFor={`cred_${field.key}`}
                        icon={KeyRound}
                        required={credentialsRequired}
                      >
                        {field.label}
                      </FormLabel>
                      <SecretSelect
                        id={`cred_${field.key}`}
                        name={`credential_secret_${field.key}`}
                        secrets={availableSecrets}
                        value={credentialSecrets[field.key] ?? ""}
                        onChange={(secretId) =>
                          setCredentialSecrets((previous) => ({
                            ...previous,
                            [field.key]: secretId,
                          }))
                        }
                        disabled={
                          resourcesLoading || resourceErrors.includes("secrets")
                        }
                        required={credentialsRequired}
                        placeholder={
                          resourcesLoading
                            ? t("loadingResources")
                            : isEditing && initialData.has_channel_credentials
                              ? t("keepExistingSecret")
                              : t("selectSecret")
                        }
                        searchPlaceholder={t("selectSecret")}
                        emptyMessage={t("noSecrets")}
                        createLabel={t("newSecret")}
                        onCreated={resources.refresh}
                      />
                      {state.errors?.[`credential_secret_${field.key}`] && (
                        <p role="alert" className="form-error">
                          {state.errors[`credential_secret_${field.key}`][0]}
                        </p>
                      )}
                    </div>
                  ))}
                </div>
                <p className="note">{t("selectCredentialsHint")}</p>
                {/* Nothing here is required: a trigger saved without its
                  connection exists but receives nothing until one is added. */}
                {!isEditing && (
                  <p className="note">{t("credentialsLaterHint")}</p>
                )}
                {resourceErrors.includes("secrets") && (
                  <p role="alert" className="form-error">
                    {t("resourcesLoadFailed")}
                  </p>
                )}
              </div>
            )}

            {!showTypePicker && showEvents && (
              <div className="space-y-2">
                <div className="flex items-center justify-between gap-3">
                  <FormLabel icon={Webhook}>{t("eventTypes")}</FormLabel>
                  <span className="note">
                    {selectedEvents.length
                      ? t("selectedEventsCount", {
                          count: selectedEvents.length,
                        })
                      : t("allEvents")}
                  </span>
                </div>
                <p className="note">{t("eventTypesHint")}</p>
                <div className="grid max-h-56 gap-x-4 gap-y-2.5 overflow-y-auto rounded-md border p-3 sm:grid-cols-2 xl:grid-cols-3">
                  {availableEvents.map((event) => (
                    <div
                      key={event}
                      className="flex min-w-0 items-center gap-2"
                    >
                      <Checkbox
                        id={`event_${event}`}
                        checked={selectedEvents.includes(event)}
                        onCheckedChange={() => toggleEvent(event)}
                      />
                      <Label
                        htmlFor={`event_${event}`}
                        className="cursor-pointer truncate font-mono text-xs font-normal"
                        title={event}
                      >
                        {event}
                      </Label>
                    </div>
                  ))}
                </div>
              </div>
            )}

            <Divider />

            <details
              data-run-settings
              open={runSettingsOpen}
              onToggle={(event) => setRunSettingsOpen(event.currentTarget.open)}
              className="group/settings"
            >
              <summary className="flex w-fit cursor-pointer list-none items-center gap-2 [&::-webkit-details-marker]:hidden">
                {/* A label is interactive content: clicks on it would never
                  reach the summary, so it lets them through. */}
                <FormLabel
                  icon={SlidersHorizontal}
                  className="pointer-events-none"
                >
                  {t("runSettings")}
                </FormLabel>
                <ChevronDown
                  aria-hidden="true"
                  className="h-4 w-4 text-muted-foreground transition-transform group-open/settings:rotate-180 motion-reduce:transition-none"
                />
              </summary>
              <div className="form-content pt-5">
                <div className="space-y-2 md:max-w-sm">
                  <FormLabel
                    htmlFor="failure_threshold"
                    icon={AlertTriangle}
                    optional
                  >
                    {t("failureThreshold")}
                  </FormLabel>
                  <Input
                    id="failure_threshold"
                    name="failure_threshold"
                    type="number"
                    min={1}
                    max={100}
                    placeholder={t("failureThresholdPlaceholder")}
                    defaultValue={initialData?.failure_threshold || ""}
                  />
                  {state.errors?.failure_threshold && (
                    <p className="form-error">
                      {state.errors.failure_threshold[0]}
                    </p>
                  )}
                </div>

                {triggerType === "webhook" && !isChannel && (
                  <div className="space-y-2">
                    <FormLabel icon={ArrowLeftRight}>
                      {t("allowedMethods")}
                    </FormLabel>
                    <div className="flex flex-wrap gap-x-4 gap-y-2">
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
                            className="cursor-pointer font-mono text-xs font-normal"
                          >
                            {method}
                          </Label>
                        </div>
                      ))}
                    </div>
                    {state.errors?.allowed_methods && (
                      <p className="form-error">
                        {state.errors.allowed_methods[0]}
                      </p>
                    )}
                  </div>
                )}

                <div className="space-y-2">
                  <FormLabel htmlFor="description" icon={FileText} optional>
                    {t("triggerDescription")}
                  </FormLabel>
                  <Textarea
                    id="description"
                    name="description"
                    defaultValue={initialData?.description ?? ""}
                    placeholder={t("triggerDescriptionPlaceholder")}
                    maxLength={1000}
                    className="h-[100px] resize-none"
                  />
                  {state.errors?.description && (
                    <p className="form-error">{state.errors.description[0]}</p>
                  )}
                </div>
              </div>
            </details>
          </div>
        </div>
        <div className="lg:h-full lg:w-[360px] lg:shrink-0">
          <TriggerExecutionContext
            selectedAgentId={selectedAgentId}
            agents={agents}
            availableMcps={availableMcps}
            availableSkills={availableSkills}
            selectedMcps={taskMcps}
            selectedSkills={taskSkills}
            selectedFiles={taskFiles}
            resourcesLoading={resourcesLoading}
            resourceErrors={resourceErrors}
            refreshKey={resources.revision}
            orchestratorControl={
              <div className="space-y-2">
                <AgentSelect
                  name="agent_id"
                  id="agent_id"
                  agents={agents}
                  value={selectedAgentId}
                  onChange={(agentId) => {
                    setSelectedAgentId(agentId);
                    setAgentMissing(false);
                  }}
                  ariaLabel={t("execution.orchestrator")}
                  placeholder={t("selectAgent")}
                  invalid={agentMissing || Boolean(state.errors?.agent_id)}
                />
                {(agentMissing || state.errors?.agent_id) && (
                  <p role="alert" className="form-error">
                    {state.errors?.agent_id?.[0] ?? t("agentRequired")}
                  </p>
                )}
              </div>
            }
            fileControl={fileControl}
            onRemoveMcp={(id) =>
              setTaskMcps((previous) =>
                previous.filter((item) => item.id !== id)
              )
            }
            onRemoveSkill={(id) =>
              setTaskSkills((previous) =>
                previous.filter((item) => item.id !== id)
              )
            }
            onClearFiles={() => setTaskFiles([])}
            onRemoveFile={(path) =>
              setTaskFiles((previous) =>
                previous.filter((file) => file !== path)
              )
            }
          />
        </div>
      </form>
    </>
  );
}
