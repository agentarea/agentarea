"use client";

import { useActionState, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { ChevronRight, Paperclip } from "lucide-react";
import type { AgentResponse, TriggerResponse } from "@/api/client/types.gen";
import { AgentSelect } from "@/components/AgentSelect";
import ConfigSheet from "@/components/ConfigSheet";
import { FileTree } from "@/components/files/file-tree";
import FormLabel from "@/components/FormLabel/FormLabel";
import { McpPicker } from "@/components/ResourcePicker/McpPicker";
import { SkillPicker } from "@/components/ResourcePicker/SkillPicker";
import { SecretSelect } from "@/components/SecretSelect";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { useAttachableResources } from "@/hooks/use-attachable-resources";
import { useToast } from "@/hooks/use-toast";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { cn } from "@/lib/utils";
import {
  composeTaskParameters,
  normalizeTaskParameters,
  type TaskParameterRef,
} from "../components/taskParameters";
import { renderTriggerIcon } from "../components/triggerDisplay";
import {
  createTriggerAction,
  listTriggerCatalogAction,
  updateTriggerAction,
  type TriggerCatalogEntry,
  type TriggerFormState,
} from "./actions";
import { CronScheduler } from "./CronScheduler";
import { TriggerExecutionContext } from "./TriggerExecutionContext";

interface CreateTriggerFormProps {
  agents: AgentResponse[];
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
const KIND_ORDER: TriggerCatalogEntry["kind"][] = [
  "schedule",
  "messaging",
  "event",
];

type SelectableResource = TaskParameterRef;
const McpIcon = ENTITY_ICONS.mcp;
const SkillIcon = ENTITY_ICONS.skill;

const TIMEZONES = [
  "UTC",
  "America/New_York",
  "America/Chicago",
  "America/Denver",
  "America/Los_Angeles",
  "Europe/London",
  "Europe/Paris",
  "Europe/Berlin",
  "Europe/Moscow",
  "Asia/Tokyo",
  "Asia/Shanghai",
  "Asia/Kolkata",
  "Australia/Sydney",
  "Pacific/Auckland",
] as const;

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
  const wt = initialData.webhook_type;
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

  const [catalog, setCatalog] = useState<TriggerCatalogEntry[]>([]);
  const [selectedId, setSelectedId] = useState("");
  const [selectedAgentId, setSelectedAgentId] = useState(
    initialData?.agent_id ?? ""
  );
  const [credentialSecrets, setCredentialSecrets] = useState<
    Record<string, string>
  >({});
  const [catalogFailed, setCatalogFailed] = useState(false);
  const [runSettingsOpen, setRunSettingsOpen] = useState(false);

  useEffect(() => {
    if (
      state.errors?.failure_threshold ||
      state.errors?.allowed_methods ||
      state.errors?.description
    )
      setRunSettingsOpen(true);
  }, [state.errors]);
  const [typeMissing, setTypeMissing] = useState(false);
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
  const [fileSearch, setFileSearch] = useState("");
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

  // Fetch catalog from backend
  useEffect(() => {
    listTriggerCatalogAction()
      .then((data) => {
        setCatalog(data);
        setCatalogFailed(false);
        if (initialData) {
          setSelectedId(resolveInitialId(data, initialData));
        }
      })
      .catch((e) => {
        // Swallowing this left an empty type dropdown that looked like the
        // product simply had no trigger types.
        console.error("Failed to load trigger catalog:", e);
        setCatalogFailed(true);
      });
  }, [initialData]);

  const refreshResourcesControl = (
    <Button
      type="button"
      variant="ghost"
      size="xs"
      disabled={resourcesLoading}
      onClick={resources.refresh}
    >
      {t("refreshResources")}
    </Button>
  );

  const selected = catalog.find((e) => e.id === selectedId);
  const triggerType = initialData?.trigger_type ?? selected?.backend_type ?? "";
  const webhookType = initialData?.webhook_type ?? selected?.webhook_type ?? "";
  // A schedule comes due carrying nothing with it, so the task text is the only
  // thing that can tell the agent what to do, and the backend rejects a
  // schedule saved without one. Two kinds are exempt because something else
  // supplies the text: webhooks get it from the call, and a poller works on
  // whatever the mailbox or feed handed it.
  const taskTextRequired =
    triggerType === "cron" &&
    !(initialData?.data_extractor ?? selected?.data_extractor);
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
    if (state.success) {
      toast({
        title: isEditing ? tSuccess("updated") : tSuccess("created"),
        variant: "success",
      });
      router.push(initialData ? `/triggers/${initialData.id}` : "/triggers");
      router.refresh();
    } else if (state.errors) {
      toast({
        title: isEditing ? tError("updateFailed") : tError("createFailed"),
        description: state.message,
        variant: "destructive",
      });
    }
  }, [state, toast, router, isEditing, initialData, tSuccess, tError]);

  // Kind is only a grouping header inside the type dropdown.
  const kindLabels: Record<string, string> = {
    schedule: "Scheduling",
    messaging: "Messaging",
    event: "Events",
  };
  const kinds = new Set(catalog.map((e) => e.kind));
  const orderedKinds = KIND_ORDER.filter((k) => kinds.has(k));

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    if (!isEditing && !selected) {
      event.preventDefault();
      setTypeMissing(true);
    }
  };

  const fileControl = (
    <ConfigSheet
      title={t("taskFiles")}
      description={t("taskFilesHint")}
      triggerComponent={
        <Button
          id="task_files"
          type="button"
          variant="ghost"
          size="xs"
          className="justify-start gap-1.5 px-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <Paperclip />
          {t("taskFilesPlaceholder")}
        </Button>
      }
    >
      <div className="flex min-h-0 flex-col gap-3 overflow-y-auto pb-6">
        <Input
          aria-label={t("searchFiles")}
          placeholder={t("searchFiles")}
          value={fileSearch}
          onChange={(event) => setFileSearch(event.target.value)}
        />
        {resourcesLoading ? (
          <p className="note">{t("loadingResources")}</p>
        ) : resourceErrors.includes("files") ? (
          <p role="alert" className="text-xs text-destructive">
            {t("resourcesLoadFailed")}
          </p>
        ) : (
          <>
            <FileTree
              files={availableFiles.filter(
                (file) =>
                  !taskFiles.includes(file.path) &&
                  file.path.toLowerCase().includes(fileSearch.toLowerCase())
              )}
              selectedPath={null}
              onSelect={(file) =>
                setTaskFiles((previous) =>
                  previous.includes(file.path)
                    ? previous
                    : [...previous, file.path]
                )
              }
            />
            {!availableFiles.some(
              (file) =>
                !taskFiles.includes(file.path) &&
                file.path.toLowerCase().includes(fileSearch.toLowerCase())
            ) && <p className="note">{t("noFiles")}</p>}
          </>
        )}
        <Link
          href="/files"
          target="_blank"
          rel="noopener noreferrer"
          className="text-xs text-primary hover:underline"
        >
          {t("manageFiles")}
        </Link>
        {refreshResourcesControl}
      </div>
    </ConfigSheet>
  );
  const mcpControl = (
    <ConfigSheet
      title={t("taskMcps")}
      description={t("taskMcpsHint")}
      triggerComponent={
        <Button
          type="button"
          variant="ghost"
          size="xs"
          className="justify-start gap-1.5 px-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <McpIcon />
          {t("taskMcpsPlaceholder")}
        </Button>
      }
    >
      <div className="min-h-0 overflow-y-auto pb-6">
        <McpPicker
          resources={resources}
          selectedIds={taskMcps.map((mcp) => mcp.id)}
          onAdd={(mcp) =>
            setTaskMcps((previous) =>
              previous.some((item) => item.id === mcp.id)
                ? previous
                : [...previous, { id: mcp.id, name: mcp.name }]
            )
          }
          onRemove={(mcp) =>
            setTaskMcps((previous) =>
              previous.filter((item) => item.id !== mcp.id)
            )
          }
        />
      </div>
    </ConfigSheet>
  );
  const skillControl = (
    <ConfigSheet
      title={t("taskSkills")}
      description={t("taskSkillsHint")}
      triggerComponent={
        <Button
          type="button"
          variant="ghost"
          size="xs"
          className="justify-start gap-1.5 px-1.5 text-xs text-muted-foreground hover:text-foreground"
        >
          <SkillIcon />
          {t("taskSkillsPlaceholder")}
        </Button>
      }
    >
      <div className="min-h-0 overflow-y-auto pb-6">
        <SkillPicker
          resources={resources}
          selectedIds={taskSkills.map((skill) => skill.id)}
          onAdd={(skill) =>
            setTaskSkills((previous) =>
              previous.some((item) => item.id === skill.id)
                ? previous
                : [
                    ...previous,
                    {
                      id: skill.id,
                      name: skill.name,
                      description: skill.description,
                    },
                  ]
            )
          }
          onRemove={(skill) =>
            setTaskSkills((previous) =>
              previous.filter((item) => item.id !== skill.id)
            )
          }
        />
      </div>
    </ConfigSheet>
  );

  return (
    <form
      id="create-trigger-form"
      action={formAction}
      onSubmit={handleSubmit}
      onInvalidCapture={(event) => {
        if ((event.target as HTMLElement).closest("details[data-run-settings]"))
          setRunSettingsOpen(true);
      }}
      className="h-full overflow-auto"
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
      <input type="hidden" name="task_parameters" value={taskParametersValue} />
      {triggerType === "webhook" && (
        <input
          type="hidden"
          name="event_types"
          value={JSON.stringify(selectedEvents)}
        />
      )}
      <div className="mx-auto grid w-full max-w-6xl gap-6 pb-10 pt-2 lg:grid-cols-[minmax(0,1fr)_20rem] lg:gap-8">
        <div className="min-w-0 space-y-6" data-task-authoring>
          <div className="grid content-start gap-2">
            <Label htmlFor="name" className="sr-only">
              {t("automationName")}
            </Label>
            <Input
              id="name"
              name="name"
              placeholder={t("automationNamePlaceholder")}
              variant="title"
              defaultValue={initialData?.name || ""}
              required
            />
            {state.errors?.name && (
              <p className="text-sm text-destructive">{state.errors.name[0]}</p>
            )}
          </div>
          <section aria-label={t("taskInstructions")} className="space-y-3">
            <div className="grid content-start gap-2">
              <FormLabel htmlFor="task_text" required={taskTextRequired}>
                {t("taskInstructions")}
              </FormLabel>
              <Textarea
                id="task_text"
                value={taskText}
                onChange={(event) => setTaskText(event.target.value)}
                placeholder={t("taskTextPlaceholder")}
                variant="document"
                rows={6}
                required={taskTextRequired}
              />
            </div>
            {state.errors?.task_parameters && (
              <p className="text-sm text-destructive">
                {state.errors.task_parameters[0]}
              </p>
            )}
          </section>
          <section
            aria-labelledby="trigger-configuration-heading"
            className="space-y-5 border-t border-border/60 pt-6"
          >
            <h2
              id="trigger-configuration-heading"
              className="text-sm font-semibold"
            >
              {t("whenToRun")}
            </h2>
            {!isEditing ? (
              <div className="grid content-start gap-2">
                <FormLabel htmlFor="trigger_type_select" required>
                  {t("triggerType")}
                </FormLabel>
                <Select
                  value={selectedId}
                  onValueChange={(value) => {
                    setSelectedId(value);
                    setTypeMissing(false);
                  }}
                >
                  <SelectTrigger id="trigger_type_select">
                    <SelectValue placeholder={t("selectType")} />
                  </SelectTrigger>
                  <SelectContent>
                    {orderedKinds.map((kind) => (
                      <SelectGroup key={kind}>
                        <SelectLabel>{kindLabels[kind] ?? kind}</SelectLabel>
                        {catalog
                          .filter((entry) => entry.kind === kind)
                          .map((entry) => (
                            <SelectItem key={entry.id} value={entry.id}>
                              <span className="flex items-center gap-2">
                                {/* The catalog owns the artwork — drawing it
                                    from a map here is how channels the map
                                    never heard of ended up as dots. */}
                                <span className="flex h-4 w-4 shrink-0 items-center justify-center text-muted-foreground">
                                  {renderTriggerIcon(
                                    entry,
                                    undefined,
                                    "h-4 w-4"
                                  )}
                                </span>
                                {entry.name}
                              </span>
                            </SelectItem>
                          ))}
                      </SelectGroup>
                    ))}
                  </SelectContent>
                </Select>

                {catalogFailed && (
                  <p role="alert" className="text-sm text-destructive">
                    {t("catalogLoadFailed")}
                  </p>
                )}
                {(typeMissing || state.errors?.trigger_type) && (
                  <p className="text-sm text-destructive">
                    {state.errors?.trigger_type?.[0] ?? t("selectType")}
                  </p>
                )}
              </div>
            ) : (
              <div className="grid content-start gap-2">
                <FormLabel>{t("triggerType")}</FormLabel>
                <p className="text-sm font-medium">
                  {selected?.name ?? initialData.trigger_type}
                </p>
              </div>
            )}
            {triggerType === "cron" && (
              <>
                <div className="grid gap-2">
                  <FormLabel required>{t("schedule")}</FormLabel>
                  <CronScheduler
                    name="cron_expression"
                    defaultValue={
                      initialData?.cron_expression ??
                      selected?.default_cron ??
                      ""
                    }
                  />
                  {state.errors?.cron_expression && (
                    <p className="text-sm text-destructive">
                      {state.errors.cron_expression[0]}
                    </p>
                  )}
                </div>

                <div className="grid gap-2 md:max-w-sm">
                  <FormLabel htmlFor="timezone">{t("timezone")}</FormLabel>
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
            {credentialFields.length > 0 && (
              <>
                {credentialFields.map((field) => (
                  <div
                    key={`${selectedId}:${field.key}`}
                    className="grid gap-2 md:max-w-sm"
                  >
                    <FormLabel
                      htmlFor={`cred_${field.key}`}
                      required={
                        !!selected?.data_extractor &&
                        !initialData?.has_channel_credentials
                      }
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
                      required={
                        !!selected?.data_extractor &&
                        !initialData?.has_channel_credentials
                      }
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
                      <p role="alert" className="text-sm text-destructive">
                        {state.errors[`credential_secret_${field.key}`][0]}
                      </p>
                    )}
                  </div>
                ))}
                {resourceErrors.includes("secrets") && (
                  <p role="alert" className="text-xs text-destructive">
                    {t("resourcesLoadFailed")}
                  </p>
                )}
              </>
            )}
            {triggerType === "webhook" && availableEvents.length > 0 && (
              <details className="group/events rounded-md border border-border/60">
                <summary className="flex cursor-pointer list-none items-center gap-2 px-3 py-2.5 text-sm [&::-webkit-details-marker]:hidden">
                  <ChevronRight
                    aria-hidden="true"
                    className="h-3.5 w-3.5 text-muted-foreground group-open/events:rotate-90"
                  />
                  <span>{t("eventTypes")}</span>
                  <span className="ml-auto text-xs text-muted-foreground">
                    {selectedEvents.length
                      ? t("selectedEventsCount", {
                          count: selectedEvents.length,
                        })
                      : t("allEvents")}
                  </span>
                </summary>
                <div className="flex max-h-48 flex-wrap gap-1.5 overflow-y-auto px-3 pb-3">
                  {availableEvents.map((event) => (
                    <button
                      key={event}
                      type="button"
                      aria-pressed={selectedEvents.includes(event)}
                      onClick={() => toggleEvent(event)}
                      className={cn(
                        "rounded-md px-2 py-1 text-xs transition-colors",
                        selectedEvents.includes(event)
                          ? "bg-primary text-primary-foreground"
                          : "bg-muted text-muted-foreground hover:text-foreground"
                      )}
                    >
                      {event}
                    </button>
                  ))}
                </div>
              </details>
            )}
          </section>
          <details
            data-run-settings
            open={runSettingsOpen}
            onToggle={(event) => setRunSettingsOpen(event.currentTarget.open)}
            className="group/settings border-t border-border/60 pt-4"
          >
            <summary className="flex cursor-pointer list-none items-center gap-2 py-2 text-sm text-muted-foreground hover:text-foreground [&::-webkit-details-marker]:hidden">
              <ChevronRight
                aria-hidden="true"
                className="h-3.5 w-3.5 group-open/settings:rotate-90"
              />
              {t("runSettings")}
            </summary>
            <div className="space-y-5 py-4">
              <div className="grid content-start gap-2">
                <FormLabel htmlFor="failure_threshold">
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
              </div>
              {triggerType === "webhook" && (
                <div className="grid gap-2">
                  <FormLabel>{t("allowedMethods")}</FormLabel>
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
              )}
              <div className="grid gap-2">
                <FormLabel htmlFor="description">
                  {t("triggerDescription")}
                </FormLabel>
                <Textarea
                  id="description"
                  name="description"
                  defaultValue={initialData?.description ?? ""}
                  placeholder={t("triggerDescriptionPlaceholder")}
                  maxLength={1000}
                />
                {state.errors?.description && (
                  <p className="text-sm text-destructive">
                    {state.errors.description[0]}
                  </p>
                )}
              </div>
            </div>
          </details>
          {state.errors?._form && (
            <div className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive">
              {state.errors._form.map((error, index) => (
                <p key={index}>{error}</p>
              ))}
            </div>
          )}
        </div>
        <div className="min-w-0 self-start border-t border-border/60 pt-4 lg:sticky lg:top-0 lg:max-h-[calc(100dvh-8rem)] lg:overflow-y-auto lg:border-t-0 lg:pt-0">
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
                  onChange={setSelectedAgentId}
                  ariaLabel={t("execution.orchestrator")}
                  placeholder={t("selectAgent")}
                />
                {state.errors?.agent_id && (
                  <p className="text-sm text-destructive">
                    {state.errors.agent_id[0]}
                  </p>
                )}
              </div>
            }
            mcpControl={mcpControl}
            skillControl={skillControl}
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
            onRemoveFile={(path) =>
              setTaskFiles((previous) =>
                previous.filter((file) => file !== path)
              )
            }
          />
        </div>
      </div>
    </form>
  );
}
