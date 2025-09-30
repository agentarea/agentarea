"use client";

import React, { useEffect, useState, useTransition } from "react";
import { Button } from "@/components/ui/button";
import { useForm, useFieldArray } from 'react-hook-form';
import { addAgent } from './actions';
import { initialState as agentInitialState } from './types';
import { generateAgentName } from './utils/agentNameGenerator';
import type { components } from '@/api/schema';
import { Card } from "@/components/ui/card";
import { 
  BasicInformation, 
  AgentTriggers, 
  ToolConfig
} from './components';
import type { AgentFormValues, EventConfig } from './types';
import { useRouter } from 'next/navigation';
import { toast } from 'sonner';

type MCPServer = components["schemas"]["MCPServerResponse"];
type LLMModelInstance = components["schemas"]["ModelInstanceResponse"];

export default function CreateAgentClient({ 
  mcpServers, 
  llmModelInstances, 
  mcpInstanceList,
  builtinTools
}: { 
  mcpServers: MCPServer[];
  llmModelInstances: LLMModelInstance[];
  mcpInstanceList: any[];
  builtinTools: any[];
}) {
  const [state, setState] = useState(agentInitialState);
  const [isPending, startTransition] = useTransition();
  const router = useRouter();

  const { register, control, setValue, handleSubmit, formState: { errors } } = useForm<AgentFormValues>({
    defaultValues: {
      name: generateAgentName(), // Генерируем имя сразу при создании формы
      description: '',
      instruction: '',
      model_id: '',
      tools_config: { mcp_server_configs: [], builtin_tools: [] },
      events_config: { events: [] },
      planning: false,
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

  // Handle form field updates (only for error states)
  useEffect(() => {
    if (state?.fieldValues && state.message !== 'Agent created successfully!') {
      // Не перезаписываем имя, если оно уже есть в форме
      if (state.fieldValues.name) {
        setValue("name", state.fieldValues.name);
      }
      setValue("description", state.fieldValues.description ?? '');
      setValue("instruction", state.fieldValues.instruction ?? '');
      setValue("model_id", state.fieldValues.model_id ?? '');
      
      if (Array.isArray(state.fieldValues.events_config?.events)) {
        const events = state.fieldValues.events_config.events.map(event => ({
          event_type: event.event_type,
          config: event.config,
          enabled: event.enabled ?? true
        }));
        setValue("events_config.events", events as unknown as EventConfig[]);
      }
      
      if (Array.isArray(state.fieldValues.tools_config?.mcp_server_configs)) {
        const configs = state.fieldValues.tools_config.mcp_server_configs.map(config => ({
          mcp_server_id: config.mcp_server_id,
          allowed_tools: config.allowed_tools || []
        }));
        setValue("tools_config.mcp_server_configs", configs);
      }
      
      const builtinTools = (state.fieldValues as any)?.tools_config?.builtin_tools;
      if (Array.isArray(builtinTools)) {
        const configs = builtinTools.map((config: any) => ({
          tool_name: config.tool_name,
          requires_user_confirmation: config.requires_user_confirmation ?? false,
          enabled: config.enabled ?? true
        }));
        setValue("tools_config.builtin_tools", configs);
      }
      
      setValue("planning", !!state.fieldValues.planning);
    }
  }, [state?.fieldValues, setValue]);

  // Handle successful creation and redirect
  useEffect(() => {
    const createdId = (state.fieldValues as any)?.id;
    if (state?.message === 'Agent created successfully!' && createdId && state.fieldValues) {
      toast.success('Agent created successfully!', {
        description: `Agent "${state.fieldValues.name}" has been created.`,
        duration: 3000,
      });
      router.push(`/agents/${createdId}`);
    }
  }, [state?.message, state?.fieldValues, state?.fieldValues?.name, router]);

  // Handle errors
  useEffect(() => {
    if (state?.errors?._form && state.errors._form.length > 0) {
      toast.error('Failed to create agent', {
        description: state.errors._form.join(', '),
        duration: 5000,
      });
    } else if (state?.message && state.message !== 'Agent created successfully!') {
      toast.error('Error', {
        description: state.message,
        duration: 5000,
      });
    }
  }, [state?.errors, state?.message]);

  // Handle form submission with react-hook-form validation
  const onSubmit = (data: AgentFormValues) => {
    startTransition(async () => {
      // Create FormData for server action
      const formData = new FormData();
      formData.append('name', data.name);
      formData.append('description', data.description || '');
      formData.append('instruction', data.instruction);
      formData.append('model_id', data.model_id);
      formData.append('planning', data.planning.toString());

      // Add tools config
      data.tools_config.mcp_server_configs.forEach((config, index) => {
        formData.append(`tools_config.mcp_server_configs[${index}].mcp_server_id`, config.mcp_server_id);
        if (config.allowed_tools) {
          config.allowed_tools.forEach((tool, toolIndex) => {
            formData.append(`tools_config.mcp_server_configs[${index}].allowed_tools[${toolIndex}].tool_name`, tool.tool_name);
            formData.append(`tools_config.mcp_server_configs[${index}].allowed_tools[${toolIndex}].requires_user_confirmation`, (tool.requires_user_confirmation ?? false).toString());
          });
        }
      });

      // Add builtin tools config
      if (data.tools_config.builtin_tools) {
        data.tools_config.builtin_tools.forEach((builtinTool, index) => {
          formData.append(`tools_config.builtin_tools[${index}].tool_name`, builtinTool.tool_name);
          if (builtinTool.requires_user_confirmation !== undefined) {
            formData.append(`tools_config.builtin_tools[${index}].requires_user_confirmation`, builtinTool.requires_user_confirmation.toString());
          }
          if (builtinTool.enabled !== undefined) {
            formData.append(`tools_config.builtin_tools[${index}].enabled`, builtinTool.enabled.toString());
          }
          if (builtinTool.disabled_methods) {
            formData.append(`tools_config.builtin_tools[${index}].disabled_methods`, JSON.stringify(builtinTool.disabled_methods));
          }
        });
      }

      // Add events config
      data.events_config.events.forEach((event, index) => {
        formData.append(`events_config.events[${index}].event_type`, event.event_type);
        if (event.config) {
          formData.append(`events_config.events[${index}].config`, JSON.stringify(event.config));
        }
        formData.append(`events_config.events[${index}].enabled`, (event.enabled ?? true).toString());
      });

      // Call server action
      const result = await addAgent(state, formData);
      setState(result);
    });
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
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
                Creating...
              </>
            ) : (
              'Create Agent'
            )}
          </Button>
        </div>

    </form>
  );
}