"use client";

import React, { useEffect, useActionState } from "react";
import { Button } from "@/components/ui/button";
import { useForm, useFieldArray } from 'react-hook-form';
import { addAgent } from './actions';
import { initialState as agentInitialState } from './state';
import type { components } from '@/api/schema';
import { Card } from "@/components/ui/card";
import { 
  BasicInformation, 
  AgentTriggers, 
  ToolConfig
} from './components';
import type { AgentFormValues, EventConfig } from './types';

type MCPServer = components["schemas"]["MCPServerResponse"];
type LLMModelInstance = components["schemas"]["ModelInstanceResponse"];

export default function CreateAgentClient({ 
  mcpServers, 
  llmModelInstances 
}: { 
  mcpServers: MCPServer[];
  llmModelInstances: LLMModelInstance[];
}) {
  const [state, formAction] = useActionState(addAgent, agentInitialState);

  const { register, control, setValue, handleSubmit, formState: { errors } } = useForm<AgentFormValues>({
    defaultValues: {
      name: '',
      description: '',
      instruction: '',
      model_id: '',
      tools_config: { mcp_server_configs: [] },
      events_config: { events: [] },
      planning: false,
    }
  });

  const { fields: toolFields, append: appendTool, remove: removeTool } =
    useFieldArray({
      control,
      name: "tools_config.mcp_server_configs",
    });
    
  const { fields: eventFields, append: appendEvent, remove: removeEvent } =
    useFieldArray({
      control,
      name: "events_config.events",
    });

  useEffect(() => {
    if (state?.fieldValues) {
      setValue("name", state.fieldValues.name ?? '');
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
      
      setValue("planning", !!state.fieldValues.planning);
    }
  }, [state?.fieldValues, setValue]);

  // Handle form submission with react-hook-form validation
  const onSubmit = (data: AgentFormValues) => {
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

    // Add events config
    data.events_config.events.forEach((event, index) => {
      formData.append(`events_config.events[${index}].event_type`, event.event_type);
      if (event.config) {
        formData.append(`events_config.events[${index}].config`, JSON.stringify(event.config));
      }
      formData.append(`events_config.events[${index}].enabled`, (event.enabled ?? true).toString());
    });

    // Call server action
    formAction(formData);
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
        <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-2 lg:gap-x-[12px] gap-[12px] items-start">
          <div className="">
            <BasicInformation 
              register={register} 
              control={control} 
              errors={errors}
              llmModelInstances={llmModelInstances}
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
                />
              </div>
            </Card>
          </div>

          {/* <div className="space-y-[12px]">
            <AgentTriggers 
              control={control} 
              errors={errors} 
              eventFields={eventFields} 
              removeEvent={removeEvent} 
              appendEvent={appendEvent} 
            />

            <ToolConfig 
              control={control} 
              errors={errors} 
              toolFields={toolFields} 
              removeTool={removeTool} 
              appendTool={appendTool} 
              mcpServers={mcpServers} 
            />

            <AdvancedSettings 
              control={control} 
              errors={errors} 
            />

            <InstructionInfo />
          </div> */}
        </div>

        <div className="max-w-6xl mx-auto flex flex-row items-end justify-end gap-4 sticky bottom-0 z-10 pt-6 pb-2 -mx-4 px-4">
          {state?.errors?._form && (
            <p className="text-red-500 mb-2 text-sm">{state.errors._form.join(', ')}</p>
          )}
          {state?.message && !state.errors?._form && (
            <p className="text-green-600 mb-2 text-sm">{state.message}</p>
          )}
          <Button
            size="lg"
            className=""
            type="submit"
          >
            Create Agent
          </Button>
        </div>

    </form>
  );
}