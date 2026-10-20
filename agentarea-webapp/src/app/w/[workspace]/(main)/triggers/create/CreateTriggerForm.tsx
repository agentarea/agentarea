"use client";

import { useActionState, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  AlertTriangle,
  ChevronRight,
  FileText,
  Paperclip,
  SlidersHorizontal,
} from "lucide-react";
import type {
  AgentResponse,
  TriggerBatchWindow,
  TriggerResponse,
} from "@/api/client/types.gen";
import { AgentSelect } from "@/components/AgentSelect";
import ConfigSheet from "@/components/ConfigSheet";
import { FileTree } from "@/components/files/file-tree";
import FormLabel from "@/components/FormLabel/FormLabel";
import SectionLoadError from "@/components/SectionLoadError";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import Link from "@/components/WorkspaceLink";
import { useAttachableResources } from "@/hooks/use-attachable-resources";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { resolveSession } from "@/lib/sourceTypes";
import {
  composeTaskParameters,
  normalizeTaskParameters,
  type TaskParameterRef,
} from "../components/taskParameters";
import { BatchSetting } from "../components/BatchSetting";
import { SessionSetting, type TriggerSession } from "../components/SessionSetting";
import { renderTriggerIcon } from "../components/triggerDisplay";
import {
  createTriggerAction,
  updateTriggerAction,
  type TriggerFormState,
} from "./actions";
import { CronScheduler } from "./CronScheduler";
import type { StreamOptions } from "./streamOptions";
import { TIMEZONES } from "./timezones";
import { TriggerExecutionContext } from "./TriggerExecutionContext";
import { requiresTaskText } from "./triggerShape";

interface CreateTriggerFormProps {
  agents: AgentResponse[];
  streams: StreamOptions;
  initialData?: TriggerResponse;
}

const INLINE_ERROR_FIELDS = new Set([
  "name",
  "trigger_type",
  "task_parameters",
  "cron_expression",
  "description",
  "agent_id",
  "stream_id",
  "batch",
]);
/** What a trigger can be: a schedule, or a subscription to a stream. */
const TRIGGER_TYPES = ["cron", "stream"] as const;

type SelectableResource = TaskParameterRef;

export function CreateTriggerForm({
  agents,
  streams,
  initialData,
}: CreateTriggerFormProps) {
  const router = useWorkspaceRouter();
  const t = useTranslations("TriggersPage.create");
  const tType = useTranslations("TriggersPage.type");
  const tError = useTranslations("TriggersPage.error");

  const isEditing = !!initialData;
  const action = isEditing ? updateTriggerAction : createTriggerAction;

  const initialState: TriggerFormState = { message: "" };
  const [state, formAction, isPending] = useActionState(action, initialState);

  const [triggerType, setTriggerType] = useState<string>(
    initialData?.trigger_type ?? ""
  );
  const [selectedAgentId, setSelectedAgentId] = useState(
    initialData?.agent_id ?? ""
  );
  const [streamId, setStreamId] = useState(initialData?.stream_id ?? "");
  // Null until someone changes it: then it follows the chosen stream's default.
  const [session, setSession] = useState<TriggerSession | null>(
    initialData?.session ?? null
  );
  const [batch, setBatch] = useState<TriggerBatchWindow | null>(
    initialData?.batch ?? null
  );
  const [runSettingsOpen, setRunSettingsOpen] = useState(false);

  useEffect(() => {
    if (
      state.errors?.failure_threshold ||
      state.errors?.description
    )
      setRunSettingsOpen(true);
  }, [state.errors]);
  // Field errors the form has no inline slot for (e.g. `config.*` from the
  // schema) are listed in the banner with their path, not dropped.
  const unplacedErrors = Object.entries(state.errors ?? {}).filter(
    ([key]) => key !== "_form" && !INLINE_ERROR_FIELDS.has(key)
  );
  const [typeMissing, setTypeMissing] = useState(false);
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
  const resources = useAttachableResources({ withFiles: true });
  const {
    mcpInstances: availableMcps,
    files: availableFiles,
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

  const taskTextRequired = requiresTaskText(triggerType);
  const stream = streams.items.find((item) => item.id === streamId);
  const effectiveSession = resolveSession(
    session,
    stream?.continuesSessions ?? false
  );
  const timezones = Array.from(
    new Set([
      ...TIMEZONES,
      ...(initialData?.timezone ? [initialData.timezone] : []),
    ])
  );

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
      // The action revalidated both paths, so the destination renders fresh.
      // A `router.refresh()` here cancels this navigation instead.
      router.push(initialData ? `/triggers/${initialData.id}` : "/triggers");
    }
  }, [state, router, initialData]);

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    if (!isEditing && !triggerType) {
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
  return (
    <>
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
        className="h-full overflow-auto"
      >
        {isEditing && <input type="hidden" name="id" value={initialData.id} />}
        <input type="hidden" name="trigger_type" value={triggerType} />
        <input
          type="hidden"
          name="task_parameters"
          value={taskParametersValue}
        />
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
                <p className="text-sm text-destructive">
                  {state.errors.name[0]}
                </p>
              )}
              {/* The type belongs beside the name: it is picked once, it decides
                which of the fields below even appear, and as a labelled block
                of its own inside "When to run" it took a whole section to
                hold one dropdown. */}
              <div className="flex flex-wrap items-center gap-2">
                {!isEditing ? (
                  <>
                    <Select
                      value={triggerType}
                      onValueChange={(value) => {
                        setTriggerType(value);
                        setTypeMissing(false);
                      }}
                    >
                      <SelectTrigger
                        id="trigger_type_select"
                        aria-label={t("triggerType")}
                        className="h-8 w-auto min-w-[13rem] gap-2 text-sm"
                      >
                        <SelectValue placeholder={t("selectType")} />
                      </SelectTrigger>
                      <SelectContent>
                        {TRIGGER_TYPES.map((type) => (
                          <SelectItem key={type} value={type}>
                            <span className="flex items-center gap-2">
                              <span className="flex h-4 w-4 shrink-0 items-center justify-center text-muted-foreground">
                                {renderTriggerIcon(
                                  { trigger_type: type },
                                  "h-4 w-4"
                                )}
                              </span>
                              {tType(type)}
                            </span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                    {(typeMissing || state.errors?.trigger_type) && (
                      <p className="text-sm text-destructive">
                        {state.errors?.trigger_type?.[0] ?? t("selectType")}
                      </p>
                    )}
                  </>
                ) : (
                  <span className="flex items-center gap-2 rounded-md bg-muted px-2 py-1 text-sm text-muted-foreground">
                    <span className="flex h-4 w-4 shrink-0 items-center justify-center">
                      {renderTriggerIcon(initialData, "h-4 w-4")}
                    </span>
                    {tType(initialData.trigger_type)}
                  </span>
                )}
              </div>
            </div>
            <section aria-label={t("taskInstructions")} className="space-y-3">
              <div className="grid content-start gap-2">
                {/* Until a type is picked neither answer is true yet, so the
                  label stays bare rather than claiming the text is optional. */}
                <FormLabel
                  htmlFor="task_text"
                  required={taskTextRequired}
                  optional={Boolean(triggerType) && !taskTextRequired}
                >
                  {t("taskInstructions")}
                </FormLabel>
                {triggerType === "stream" && (
                  <p className="text-xs text-muted-foreground">
                    {t("taskTextFromStream")}
                  </p>
                )}
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
              {triggerType === "stream" && (
                <div className="grid gap-2 md:max-w-sm">
                  <FormLabel htmlFor="stream_id" required>
                    {t("stream")}
                  </FormLabel>
                  {/* The binding is fixed once saved: an update cannot move a
                      trigger to another stream. */}
                  <Select
                    name="stream_id"
                    value={streamId}
                    onValueChange={setStreamId}
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
                  {streams.error && (
                    <SectionLoadError message={streams.error} />
                  )}
                  <p className="text-xs text-muted-foreground">
                    {t("streamHint")}
                  </p>
                  {state.errors?.stream_id && (
                    <p className="text-sm text-destructive">
                      {state.errors.stream_id[0]}
                    </p>
                  )}
                </div>
              )}
              {triggerType === "stream" && (
                <SessionSetting
                  id="session"
                  name="session"
                  value={effectiveSession}
                  onChange={setSession}
                />
              )}
              {triggerType === "stream" && (
                <BatchSetting
                  id="batch"
                  name="batch"
                  value={batch}
                  onChange={setBatch}
                />
              )}
              {state.errors?.batch && (
                <p className="text-sm text-destructive">
                  {state.errors.batch[0]}
                </p>
              )}
              {triggerType === "cron" && (
                <>
                  <div className="grid gap-2">
                    <FormLabel required>{t("schedule")}</FormLabel>
                    <CronScheduler
                      name="cron_expression"
                      defaultValue={initialData?.cron_expression ?? ""}
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
                  className="h-3.5 w-3.5 transition-transform group-open/settings:rotate-90 motion-reduce:transition-none"
                />
                <SlidersHorizontal aria-hidden="true" className="h-3.5 w-3.5" />
                {t("runSettings")}
              </summary>
              <div className="space-y-5 py-4">
                <div className="grid content-start gap-2">
                  <FormLabel htmlFor="failure_threshold" icon={AlertTriangle}>
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
                <div className="grid gap-2">
                  <FormLabel htmlFor="description" icon={FileText}>
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
            {state.errors && (
              <div
                role="alert"
                className="rounded-md border border-destructive/40 bg-destructive/5 px-3 py-2 text-sm text-destructive"
              >
                {state.errors._form ? (
                  state.errors._form.map((error, index) => (
                    <p key={index}>{error}</p>
                  ))
                ) : (
                  <p>
                    {isEditing
                      ? tError("updateFailed")
                      : tError("createFailed")}
                    {state.message ? `: ${state.message}` : ""}
                  </p>
                )}
                {unplacedErrors.length > 0 && (
                  <ul className="mt-1 list-disc space-y-0.5 pl-5">
                    {unplacedErrors.map(([path, messages]) => (
                      <li key={path}>
                        <span className="font-mono">{path}</span>:{" "}
                        {messages.join(", ")}
                      </li>
                    ))}
                  </ul>
                )}
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
    </>
  );
}
