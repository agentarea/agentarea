"use client";

import type {
  AgentPresetResponse,
  McpServerInstanceResponse,
  McpServerResponse,
  ModelInstanceResponse,
} from "@/api/client/types.gen";
import React, { useEffect, useRef, useState, useTransition } from "react";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { useFieldArray, useForm } from "react-hook-form";
import { toast } from "sonner";
import FullChat from "@/components/Chat/FullChat";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import Divider from "@/components/ui/divider";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import type { TriggerCatalogEntry } from "@/app/w/[workspace]/(main)/triggers/create/actions";
import {
  AgentTriggersLink,
  BasicInformation,
  PresetPicker,
  SkillsConfig,
  ToolConfig,
  TriggersConfig,
} from "../create/components";
import {
  hasIncompleteTriggers,
  toTriggerDrafts,
  type TriggerDraft,
} from "../create/components/TriggersConfig";
import type { AddAgentFormState } from "../create/actions";
import type { AgentFormValues, AgentSkill } from "../create/types";
import { preferredModelId, presetFormValues } from "../create/utils/agentPreset";
import { useChat } from "./ChatContext";

type MCPServer = McpServerResponse;
type LLMModelInstance = ModelInstanceResponse;

interface AgentFormProps {
  mcpServers: MCPServer[];
  llmModelInstances: LLMModelInstance[];
  mcpInstanceList: McpServerInstanceResponse[];
  builtinTools: unknown[];
  initialData?: Partial<AgentFormValues>;
  agentId?: string;
  /** Create only: presets and trigger types, each `null` when it failed to load. */
  create?: {
    presets: AgentPresetResponse[] | null;
    triggerCatalog: TriggerCatalogEntry[] | null;
  };
  /** Edit only: where this agent's triggers are managed. */
  triggersHref?: string;
  onSubmit: (data: AgentFormValues) => Promise<AddAgentFormState>;
  submitButtonText?: string;
  submitButtonLoadingText?: string;
  onSuccess?: (result: AddAgentFormState) => void;
  onError?: (error: unknown) => void;
  isLoading?: boolean;
  className?: string;
  placeholder?: string;
  welcomeComponent?: React.ReactNode;
}

export default function AgentForm({
  className,
  mcpServers,
  llmModelInstances,
  mcpInstanceList,
  builtinTools,
  initialData,
  agentId,
  create,
  triggersHref,
  onSubmit,
  onSuccess,
  onError,
  isLoading = false,
  placeholder,
  welcomeComponent,
}: AgentFormProps) {
  const [_, startTransition] = useTransition();
  const router = useWorkspaceRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const isMobile = useIsMobile();
  const { isChatSheetOpen, setIsChatSheetOpen } = useChat();
  const {
    register,
    control,
    setValue,
    getValues,
    handleSubmit,
    watch,
    formState: { errors },
  } = useForm<AgentFormValues>({
    defaultValues: {
      name: initialData?.name || "",
      description: initialData?.description || "",
      instruction: initialData?.instruction || "",
      model_id: initialData?.model_id || "",
      tools_config: initialData?.tools_config || {
        mcp_server_configs: [],
        builtin_tools: [],
      },
      planning: initialData?.planning || false,
      a2ui_enabled: initialData?.a2ui_enabled || false,
    },
  });

  const {
    fields: toolFields,
    append: appendTool,
    remove: removeTool,
    replace: replaceTools,
  } = useFieldArray({
    control,
    name: "tools_config.mcp_server_configs",
  });

  const {
    fields: builtinToolFields,
    append: appendBuiltinTool,
    remove: removeBuiltinTool,
    replace: replaceBuiltinTools,
  } = useFieldArray({
    control,
    name: "tools_config.builtin_tools",
  });

  const {
    fields: openapiFields,
    append: appendOpenapiTool,
    remove: removeOpenapiTool,
    replace: replaceOpenapiTools,
  } = useFieldArray({
    control,
    name: "tools_config.openapi_configs",
  });

  // Watch agent name for chat header
  const watchedName = watch("name");
  const [agentName, setAgentName] = useState("");

  // Skills state (managed separately from react-hook-form)
  const [selectedSkills, setSelectedSkills] = useState<AgentSkill[]>(
    initialData?.skills || []
  );

  const [triggerDrafts, setTriggerDrafts] = useState<TriggerDraft[]>(() =>
    toTriggerDrafts(initialData?.triggers ?? [])
  );
  const [showTriggerErrors, setShowTriggerErrors] = useState(false);
  const [selectedPresetId, setSelectedPresetId] = useState<string | null>(
    null
  );

  useEffect(() => {
    setAgentName(watchedName || "New Agent");
  }, [watchedName]);

  const applyPreset = (preset: AgentPresetResponse | null) => {
    const values = presetFormValues(preset);
    if (values.instruction !== undefined) {
      setValue("instruction", values.instruction);
    }
    replaceTools(values.tools_config.mcp_server_configs);
    replaceBuiltinTools(values.tools_config.builtin_tools ?? []);
    replaceOpenapiTools(values.tools_config.openapi_configs ?? []);
    setValue("tools_config.carried_tools", values.tools_config.carried_tools);
    setSelectedSkills(values.skills);
    setTriggerDrafts(toTriggerDrafts(values.triggers));
    setShowTriggerErrors(false);
    const modelId = preset
      ? preferredModelId(preset, llmModelInstances)
      : null;
    if (modelId && !getValues("model_id")) setValue("model_id", modelId);
    setSelectedPresetId(preset?.id ?? null);
  };

  // Show loading spinner if data is still loading (hooks are already initialized above)
  if (isLoading) {
    return (
      <div className="flex h-64 items-center justify-center">
        <LoadingSpinner />
      </div>
    );
  }

  // Handle form submission with react-hook-form validation
  const handleFormSubmit = (data: AgentFormValues) => {
    const form = formRef.current;
    if (!form) return;

    if (
      create &&
      hasIncompleteTriggers(triggerDrafts, create.triggerCatalog ?? [])
    ) {
      setShowTriggerErrors(true);
      return;
    }

    // Set form data attribute and dispatch event SYNCHRONOUSLY before async operations
    form.setAttribute("data-submitting", "true");
    form.dispatchEvent(
      new CustomEvent("form-submitting", { detail: { isSubmitting: true } })
    );

    // Include skills in the submission data
    const dataWithSkills = {
      ...data,
      skills: selectedSkills,
      ...(create ? { triggers: triggerDrafts.map((draft) => draft.spec) } : {}),
    };

    startTransition(async () => {
      let shouldKeepSubmitting = false;
      try {
        const result = await onSubmit(dataWithSkills);

        if (result?.message?.includes("success")) {
          toast.success("Agent saved successfully!", {
            description: `Agent "${data.name}" has been updated.`,
            duration: 3000,
          });

          if (onSuccess) {
            // Check if this is a creation (has id in result) - keep submitting state until navigation
            const createdId = result.fieldValues?.id;
            if (createdId) {
              shouldKeepSubmitting = true;
            }
            onSuccess(result);
          }
        } else if (result?.errors?._form && result.errors._form.length > 0) {
          toast.error("Failed to save agent", {
            description: result.errors._form.join(", "),
            duration: 5000,
          });

          if (onError) {
            onError(result);
          }
        } else if (result?.message && !result.message.includes("success")) {
          toast.error("Error", {
            description: result.message,
            duration: 5000,
          });

          if (onError) {
            onError(result);
          }
        }
      } catch (error) {
        console.error("Agent save failed", error);
        toast.error("Unexpected error", {
          description: "An unexpected error occurred while saving the agent.",
          duration: 5000,
        });

        if (onError) {
          onError(error);
        }
      } finally {
        // Remove form data attribute when submission is complete
        // But keep it if this is a successful creation (will navigate away)
        if (!shouldKeepSubmitting && formRef.current) {
          formRef.current.removeAttribute("data-submitting");
          formRef.current.dispatchEvent(
            new CustomEvent("form-submitting", {
              detail: { isSubmitting: false },
            })
          );
        }
      }
    });
  };

  // Chat content component
  const chatContent = (
    <>
      <div className="min-h-[40px] text-sm flex items-center gap-2 border-b border-zinc-200 bg-white px-4 dark:border-zinc-700 dark:bg-zinc-800">
        Test{" "}
        {agentName ? (
          <span className="font-bold">{agentName}</span>
        ) : (
          "New Agent"
        )}
      </div>
      <div className="relative h-full py-5 px-3 flex-1 overflow-auto">
        <div className="absolute inset-0 bg-[url('/lines.png')] dark:bg-[url('/lines-dark.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 pointer-events-none" />
        <div className="relative z-1 h-full">
          <FullChat
            agent={{ id: agentId || "new", name: agentName }}
            placeholder={placeholder || `Write a new task for ${agentName}`}
            welcomeComponent={welcomeComponent}
          />
        </div>
      </div>
    </>
  );

  return (
    <>
      <ResizablePanelGroup
        direction="horizontal"
        className={cn("h-full w-full", className)}
      >
        <ResizablePanel
          defaultSize={isMobile ? 100 : 60}
          minSize={isMobile ? 100 : 30}
        >
          <form
            ref={formRef}
            id="agent-form"
            onSubmit={handleSubmit(handleFormSubmit)}
            className="overflow-auto h-full py-5 pr-5"
          >
            {create && create.presets?.length !== 0 && (
              <>
                <PresetPicker
                  presets={create.presets}
                  selectedId={selectedPresetId}
                  onSelect={applyPreset}
                />
                <Divider />
              </>
            )}
            <BasicInformation
              register={register}
              control={control}
              errors={errors}
              setValue={setValue}
              llmModelInstances={llmModelInstances}
              onOpenConfigSheet={() => {}}
              onRefreshModels={() => router.refresh()}
            />
            <Divider />
            {create ? (
              <>
                <TriggersConfig
                  catalog={create.triggerCatalog}
                  drafts={triggerDrafts}
                  onDraftsChange={setTriggerDrafts}
                  showErrors={showTriggerErrors}
                />
                <Divider />
              </>
            ) : (
              triggersHref && (
                <>
                  <AgentTriggersLink href={triggersHref} />
                  <Divider />
                </>
              )
            )}
            <ToolConfig
              control={control}
              setValue={setValue}
              getValues={getValues}
              errors={errors}
              toolFields={toolFields}
              removeTool={removeTool}
              appendTool={appendTool}
              mcpServers={mcpServers}
              mcpInstanceList={mcpInstanceList}
              builtinTools={builtinTools}
              builtinToolFields={builtinToolFields}
              removeBuiltinTool={removeBuiltinTool}
              appendBuiltinTool={appendBuiltinTool}
              openapiFields={openapiFields}
              appendOpenapiTool={appendOpenapiTool}
              removeOpenapiTool={removeOpenapiTool}
            />
            <Divider />
            <SkillsConfig
              selectedSkills={selectedSkills}
              onSkillsChange={setSelectedSkills}
            />
            {/* Submit button moved to header controls */}
          </form>
        </ResizablePanel>
        {!isMobile && (
          <>
            <ResizableHandle withHandle />
            <ResizablePanel defaultSize={40} minSize={20}>
              <div className="overflow-hidden h-full flex flex-col border-l border-zinc-200 dark:border-zinc-700">
                {chatContent}
              </div>
            </ResizablePanel>
          </>
        )}
      </ResizablePanelGroup>

      {/* Mobile chat sheet */}
      <Sheet
        open={isMobile ? isChatSheetOpen : false}
        onOpenChange={setIsChatSheetOpen}
      >
        <SheetContent
          side="right"
          className="w-full sm:max-w-lg flex flex-col p-0"
        >
          <SheetHeader className="sr-only">
            <SheetTitle>{agentName} Chat</SheetTitle>
          </SheetHeader>
          <div className="overflow-hidden h-full flex flex-col">
            {chatContent}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
