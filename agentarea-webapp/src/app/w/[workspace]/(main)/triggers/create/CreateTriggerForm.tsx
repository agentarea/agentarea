"use client";

import { useActionState, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import {
  AlertTriangle,
  CalendarClock,
  ChevronDown,
  FileText,
  Globe,
  MessageSquare,
  Paperclip,
  SlidersHorizontal,
  Tag,
} from "lucide-react";
import type {
  AgentResponse,
  TriggerBatchWindow,
  TriggerResponse,
} from "@/api/client/types.gen";
import { AgentSelect } from "@/components/AgentSelect";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import { FilePickerPanel } from "@/components/ResourcePicker/FilePickerPanel";
import SectionLoadError from "@/components/SectionLoadError";
import { Button } from "@/components/ui/button";
import Divider from "@/components/ui/divider";
import type { GroupedSelectGroup } from "@/components/ui/grouped-select";
import { Input } from "@/components/ui/input";
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
import { resolveSession } from "@/lib/sourceTypes";
import { BatchSetting } from "../components/BatchSetting";
import {
  SessionSetting,
  type TriggerSession,
} from "../components/SessionSetting";
import {
  composeTaskParameters,
  normalizeTaskParameters,
  type TaskParameterRef,
} from "../components/taskParameters";
import { renderTriggerIcon } from "../components/triggerDisplay";
import { LANE_ICON } from "../components/TriggersTypeFilter";
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
import { TriggerTypeSelect } from "./TriggerTypeSelect";

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
  "failure_threshold",
  "batch",
]);
/**
 * What a trigger can be, grouped as the trigger list's lanes are: a schedule,
 * or a subscription to a stream.
 */
const TYPE_KINDS = [
  { lane: "schedule", label: "schedules", types: ["cron"] },
  { lane: "event", label: "events", types: ["stream"] },
] as const;

type SelectableResource = TaskParameterRef;

export function CreateTriggerForm({
  agents,
  streams,
  initialData,
}: CreateTriggerFormProps) {
  const router = useWorkspaceRouter();
  const t = useTranslations("TriggersPage.create");
  const tType = useTranslations("TriggersPage.type");
  const tFilter = useTranslations("TriggersPage.filter");
  const tError = useTranslations("TriggersPage.error");

  const isEditing = !!initialData;
  const action = isEditing ? updateTriggerAction : createTriggerAction;

  const initialState: TriggerFormState = { message: "" };
  const [state, formAction, isPending] = useActionState(action, initialState);

  const [triggerType, setTriggerType] = useState<string>(
    initialData?.trigger_type ?? ""
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
    if (state.errors?.failure_threshold || state.errors?.description)
      setRunSettingsOpen(true);
  }, [state.errors]);
  // Field errors the form has no inline slot for (e.g. `config.*` from the
  // schema) are listed in the banner with their path, not dropped.
  const unplacedErrors = Object.entries(state.errors ?? {}).filter(
    ([key]) => key !== "_form" && !INLINE_ERROR_FIELDS.has(key)
  );
  const [typeMissing, setTypeMissing] = useState(false);
  const [agentMissing, setAgentMissing] = useState(false);
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

  // The type's own fields wait for a type; an edit always has one.
  const hasType = isEditing || !!triggerType;

  const typeGroups: GroupedSelectGroup[] = TYPE_KINDS.map(
    ({ lane, label, types }) => {
      const Icon = LANE_ICON[lane] ?? ENTITY_ICONS.trigger;
      return {
        id: lane,
        label: tFilter(label),
        icon: <Icon className="h-4 w-4 text-muted-foreground" />,
        items: types.map((type) => ({
          id: type,
          label: tType(type),
          icon: renderTriggerIcon(
            { trigger_type: type },
            "h-4 w-4 text-muted-foreground"
          ),
        })),
      };
    }
  );

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
    if (!triggerType) {
      setTypeMissing(true);
      document
        .getElementById("trigger-type-field")
        ?.scrollIntoView({ block: "start", behavior: "smooth" });
      document
        .getElementById("trigger_type_select")
        ?.focus({ preventScroll: true });
    }
    if (!triggerType || !selectedAgentId) event.preventDefault();
  };

  const fileControl = (
    // Non-modal and unshaded, like the task's attach sheet: the form behind
    // stays in view while files are picked.
    <Sheet modal={false}>
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
      <SheetContent
        side="right"
        hideOverlay
        className="flex flex-col gap-0 overflow-hidden p-0 sm:w-[420px] sm:max-w-[420px]"
      >
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
        <input
          type="hidden"
          name="task_parameters"
          value={taskParametersValue}
        />
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
              {triggerType === "stream" && (
                <p className="note">{t("taskTextFromStream")}</p>
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
              <FormLabel
                htmlFor="trigger_type_select"
                icon={ENTITY_ICONS.trigger}
                required={!isEditing}
              >
                {t("triggerType")}
              </FormLabel>
              {(typeMissing || state.errors?.trigger_type) && (
                <p role="alert" className="form-error">
                  {state.errors?.trigger_type?.[0] ?? t("selectType")}
                </p>
              )}
              <TriggerTypeSelect
                id="trigger_type_select"
                groups={typeGroups}
                value={triggerType}
                onValueChange={(type) => {
                  setTriggerType(type);
                  if (!nameEdited)
                    setName(t("suggestedName", { type: tType(type) }));
                  setTypeMissing(false);
                }}
                placeholder={t("selectType")}
                // An edit cannot change the type: shown, not offered.
                disabled={isEditing}
                invalid={typeMissing || !!state.errors?.trigger_type}
              />
            </div>

            {hasType && triggerType === "stream" && (
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
                {streams.error && <SectionLoadError message={streams.error} />}
                <p className="note">{t("streamHint")}</p>
                {state.errors?.stream_id && (
                  <p className="form-error">{state.errors.stream_id[0]}</p>
                )}
              </div>
            )}

            {hasType && triggerType === "stream" && (
              <SessionSetting
                id="session"
                name="session"
                value={effectiveSession}
                onChange={setSession}
              />
            )}

            {hasType && triggerType === "stream" && (
              <div className="space-y-2">
                <BatchSetting
                  id="batch"
                  name="batch"
                  value={batch}
                  onChange={setBatch}
                />
                {state.errors?.batch && (
                  <p className="form-error">{state.errors.batch[0]}</p>
                )}
              </div>
            )}

            {hasType && triggerType === "cron" && (
              <>
                <div className="grid grid-cols-[minmax(0,1fr)] gap-2">
                  <FormLabel icon={CalendarClock} required>
                    {t("schedule")}
                  </FormLabel>
                  <CronScheduler
                    name="cron_expression"
                    defaultValue={initialData?.cron_expression ?? ""}
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
