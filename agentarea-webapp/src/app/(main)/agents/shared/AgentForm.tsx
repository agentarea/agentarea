"use client";

import React, { useTransition } from "react";
import { useRouter } from "next/navigation";
import { useFieldArray, useForm } from "react-hook-form";
import { toast } from "sonner";
import type { components } from "@/api/schema";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  AgentTriggers,
  BasicInformation,
  ToolConfig,
} from "../create/components";
import type { AgentFormValues, EventConfig } from "../create/types";

type MCPServer = components["schemas"]["MCPServerResponse"];
type LLMModelInstance = components["schemas"]["ModelInstanceResponse"];

interface AgentFormProps {
  mcpServers: MCPServer[];
  llmModelInstances: LLMModelInstance[];
  mcpInstanceList: any[];
  builtinTools: any[];
  initialData?: Partial<AgentFormValues>;
  onSubmit: (data: AgentFormValues) => Promise<any>;
  submitButtonText?: string;
  submitButtonLoadingText?: string;
  onSuccess?: (result: any) => void;
  onError?: (error: any) => void;
  isLoading?: boolean;
}

export default function AgentForm({
  mcpServers,
  llmModelInstances,
  mcpInstanceList,
  builtinTools,
  initialData,
  onSubmit,
  submitButtonText = "Save Agent",
  submitButtonLoadingText = "Saving...",
  onSuccess,
  onError,
  isLoading = false,
}: AgentFormProps) {
  const [isPending, startTransition] = useTransition();
  const router = useRouter();
  const {
    register,
    control,
    setValue,
    handleSubmit,
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
    startTransition(async () => {
      try {
        const result = await onSubmit(data);

        if (result?.message?.includes("success")) {
          toast.success("Agent saved successfully!", {
            description: `Agent "${data.name}" has been updated.`,
            duration: 3000,
          });

          if (onSuccess) {
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
      }
    });
  };

  return (
    <form id="agent-form" onSubmit={handleSubmit(handleFormSubmit)}>
      <div className="mx-auto grid max-w-6xl grid-cols-1 items-start gap-[12px] lg:grid-cols-2 lg:gap-x-[12px]">
        <div className="">
          <BasicInformation
            register={register}
            control={control}
            errors={errors}
            setValue={setValue}
            llmModelInstances={llmModelInstances}
            onOpenConfigSheet={() => {}}
            onRefreshModels={() => router.refresh()}
          />
        </div>
        <div className="space-y-[12px]">
          <Card className="px-0">
            <div className="px-6">
              <AgentTriggers
                control={control}
                errors={errors}
                eventFields={eventFields}
                removeEvent={removeEvent}
                appendEvent={appendEvent}
              />
            </div>
            <div className="my-6 h-[1px] w-full bg-slate-200" />
            <div className="px-6">
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
            </div>
          </Card>
        </div>
      </div>

      {/* Submit button moved to header controls */}
    </form>
  );
}
