"use client";

import React, { useEffect, useRef, useState, useTransition } from "react";
import { useRouter } from "next/navigation";
import { useFieldArray, useForm } from "react-hook-form";
import { toast } from "sonner";
import type { components } from "@/api/schema";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import FullChat from "@/components/Chat/FullChat";
import Divider from "@/components/ui/divider";
import {
  ResizablePanelGroup,
  ResizablePanel,
  ResizableHandle,
} from "@/components/ui/resizable";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";
import { useChat } from "./ChatContext";
import {
  AgentTriggers,
  BasicInformation,
  ToolConfig,
} from "../create/components";
import type { AgentFormValues } from "../create/types";

type MCPServer = components["schemas"]["MCPServerResponse"];
type LLMModelInstance = components["schemas"]["ModelInstanceResponse"];

interface AgentFormProps {
  mcpServers: MCPServer[];
  llmModelInstances: LLMModelInstance[];
  mcpInstanceList: any[];
  builtinTools: any[];
  initialData?: Partial<AgentFormValues>;
  agentId?: string;
  onSubmit: (data: AgentFormValues) => Promise<any>;
  submitButtonText?: string;
  submitButtonLoadingText?: string;
  onSuccess?: (result: any) => void;
  onError?: (error: any) => void;
  isLoading?: boolean;
  className?: string;
}

export default function AgentForm({
  className,
  mcpServers,
  llmModelInstances,
  mcpInstanceList,
  builtinTools,
  initialData,
  agentId,
  onSubmit,
  submitButtonText = "Save Agent",
  submitButtonLoadingText = "Saving...",
  onSuccess,
  onError,
  isLoading = false,
}: AgentFormProps) {
  const [_, startTransition] = useTransition();
  const router = useRouter();
  const formRef = useRef<HTMLFormElement>(null);
  const isMobile = useIsMobile();
  const { isChatSheetOpen, setIsChatSheetOpen } = useChat();
  const {
    register,
    control,
    setValue,
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
      events_config: initialData?.events_config || { events: [] },
      planning: initialData?.planning || false,
    },
  });

  const {
    fields: toolFields,
    append: appendTool,
    remove: removeTool,
  } = useFieldArray({
    control,
    name: "tools_config.mcp_server_configs",
  });

  const {
    fields: builtinToolFields,
    append: appendBuiltinTool,
    remove: removeBuiltinTool,
  } = useFieldArray({
    control,
    name: "tools_config.builtin_tools",
  });

  const {
    fields: eventFields,
    append: appendEvent,
    remove: removeEvent,
  } = useFieldArray({
    control,
    name: "events_config.events",
  });

  // Watch agent name for chat header
  const watchedName = watch("name");
  const [agentName, setAgentName] = useState("");

  useEffect(() => {
    setAgentName(watchedName || "New Agent");
  }, [watchedName]);

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

    // Set form data attribute and dispatch event SYNCHRONOUSLY before async operations
    form.setAttribute("data-submitting", "true");
    form.dispatchEvent(new CustomEvent("form-submitting", { detail: { isSubmitting: true } }));

    startTransition(async () => {
      let shouldKeepSubmitting = false;
      try {
        const result = await onSubmit(data);

        if (result?.message?.includes("success")) {
          toast.success("Agent saved successfully!", {
            description: `Agent "${data.name}" has been updated.`,
            duration: 3000,
          });

          if (onSuccess) {
            // Check if this is a creation (has id in result) - keep submitting state until navigation
            const createdId = (result.fieldValues as any)?.id;
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
            new CustomEvent("form-submitting", { detail: { isSubmitting: false } })
          );
        }
      }
    });
  };

  // Chat content component
  const chatContent = (
    <>
      <div className="min-h-[40px] text-sm flex items-center gap-2 border-b border-zinc-200 bg-white px-4 dark:border-zinc-700 dark:bg-zinc-800">
        Test {agentName ? <span className="font-bold">{agentName}</span> : "New Agent"}
      </div>
      <div className="relative h-full py-5 px-3 flex-1 overflow-auto">
        <div className="absolute inset-0 bg-[url('/lines.png')] dark:bg-[url('/lines-dark.png')] bg-[size:450px_450px] bg-center bg-repeat opacity-20 pointer-events-none" />
        <div className="relative z-1 h-full">
          <FullChat 
            agent={{ id: agentId || "new", name: agentName }} 
            placeholder={`Write a new task for ${agentName}`}
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
        <ResizablePanel defaultSize={isMobile ? 100 : 60} minSize={isMobile ? 100 : 30}>
          <form
            ref={formRef}
            id="agent-form"
            onSubmit={handleSubmit(handleFormSubmit)}
            className="overflow-auto h-full py-5 pr-5"
          >
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
            <AgentTriggers
              control={control}
              errors={errors}
              eventFields={eventFields}
              removeEvent={removeEvent}
              appendEvent={appendEvent}
            />
            <Divider />
            <ToolConfig
              control={control}
              setValue={setValue}
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
      <Sheet open={isMobile ? isChatSheetOpen : false} onOpenChange={setIsChatSheetOpen}>
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
