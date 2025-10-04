"use client";

import React, { useEffect, useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { useForm, useFieldArray } from 'react-hook-form';
import { Card } from "@/components/ui/card";
import { 
  BasicInformation, 
  AgentTriggers, 
  ToolConfig
} from '../create/components';
import type { AgentFormValues, EventConfig } from '../create/types';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';
import type { components } from '@/api/schema';
import { LoadingSpinner } from '@/components/LoadingSpinner';

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
  submitButtonText = 'Save Agent',
  submitButtonLoadingText = 'Saving...',
  onSuccess,
  onError,
  isLoading = false
}: AgentFormProps) {
  const [isPending, startTransition] = useTransition();
  const router = useRouter();
  const { register, control, setValue, handleSubmit, formState: { errors } } = useForm<AgentFormValues>({
    defaultValues: {
      name: initialData?.name || '',
      description: initialData?.description || '',
      instruction: initialData?.instruction || '',
      model_id: initialData?.model_id || '',
      tools_config: initialData?.tools_config || { mcp_server_configs: [], builtin_tools: [] },
      events_config: initialData?.events_config || { events: [] },
      planning: initialData?.planning || false,
    }
  });

  const { fields: toolFields, append: appendTool, remove: removeTool } =
    useFieldArray({
      control,
      name: "tools_config.mcp_server_configs",
    });

  const { fields: builtinToolFields, append: appendBuiltinTool, remove: removeBuiltinTool } =
    useFieldArray({
      control,
      name: "tools_config.builtin_tools",
    });
    
  const { fields: eventFields, append: appendEvent, remove: removeEvent } =
    useFieldArray({
      control,
      name: "events_config.events",
    });

  // Show loading spinner if data is still loading (hooks are already initialized above)
  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-64">
        <LoadingSpinner />
      </div>
    );
  }

  // Handle form submission with react-hook-form validation
  const handleFormSubmit = (data: AgentFormValues) => {
    startTransition(async () => {
      try {
        const result = await onSubmit(data);
        
        if (result?.message?.includes('success')) {
          toast.success('Agent saved successfully!', {
            description: `Agent "${data.name}" has been updated.`,
            duration: 3000,
          });
          
          if (onSuccess) {
            onSuccess(result);
          }
        } else if (result?.errors?._form && result.errors._form.length > 0) {
          toast.error('Failed to save agent', {
            description: result.errors._form.join(', '),
            duration: 5000,
          });
          
          if (onError) {
            onError(result);
          }
        } else if (result?.message && !result.message.includes('success')) {
          toast.error('Error', {
            description: result.message,
            duration: 5000,
          });
          
          if (onError) {
            onError(result);
          }
        }
      } catch (error) {
        toast.error('Unexpected error', {
          description: 'An unexpected error occurred while saving the agent.',
          duration: 5000,
        });
        
        if (onError) {
          onError(error);
        }
      }
    });
  };

  return (
    <form onSubmit={handleSubmit(handleFormSubmit)}>
        <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-2 lg:gap-x-[12px] gap-[12px] items-start">
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
              <div className="my-6 w-full h-[1px] bg-slate-200" />
              <div className="px-6">
                <ToolConfig 
                  control={control} 
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

        <div className="max-w-6xl mx-auto flex flex-row items-end justify-end gap-4 sticky bottom-0 z-10 pt-6 pb-2 -mx-4 px-4">
          <Button
            size="lg"
            className=""
            type="submit"
            disabled={isPending}
          >
            {isPending ? (
              <>
                <svg className="animate-spin -ml-1 mr-3 h-5 w-5 text-white" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                </svg>
                {submitButtonLoadingText}
              </>
            ) : (
              submitButtonText
            )}
          </Button>
        </div>

    </form>
  );
}
