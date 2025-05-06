"use client";

import React, { useEffect, useActionState } from "react";
import { Button } from "@/components/ui/button";
import { useForm, useFieldArray } from 'react-hook-form';
import { addAgent } from './actions';
import { initialState as agentInitialState } from './state';
import type { components } from '@/api/schema';
import { 
  BasicInformation, 
  AgentTriggers, 
  ToolConfig, 
  AdvancedSettings, 
  InstructionInfo 
} from './components';
import type { AgentFormValues, EventConfig } from './types';

type MCPServer = components["schemas"]["MCPServerResponse"];

export default function CreateAgentClient({ mcpServers }: { mcpServers: MCPServer[] }) {
  const [state, formAction] = useActionState(addAgent, agentInitialState);

  const { register, control, setValue, formState: { errors } } = useForm<AgentFormValues>({
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
        setValue("events_config.events", state.fieldValues.events_config.events as EventConfig[]);
      }
      
      if (Array.isArray(state.fieldValues.tools_config?.mcp_server_configs)) {
        const configs = state.fieldValues.tools_config.mcp_server_configs.map(config => ({
          mcp_server_id: config.mcp_server_id,
          api_key: '',
          config: config.config
        }));
        setValue("tools_config.mcp_server_configs", configs);
      }
      
      setValue("planning", !!state.fieldValues.planning);
    }
  }, [state?.fieldValues, setValue]);

  return (
    <form action={formAction}>
        <div className="max-w-6xl mx-auto grid grid-cols-1 lg:grid-cols-2 gap-[12px] items-start">
          <div className="">
            <BasicInformation 
              register={register} 
              control={control} 
              errors={errors} 
            />
          </div>

          <div className="space-y-[12px]">
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
          </div>
        </div>

        <div className="max-w-6xl mx-auto flex flex-col items-end sticky bottom-0 z-10 bg-gradient-to-t from-white/90 via-white/60 to-transparent pt-6 pb-2 -mx-4 px-4">
          {state?.errors?._form && (
            <p className="text-red-500 mb-2 font-medium">{state.errors._form.join(', ')}</p>
          )}
          {state?.message && !state.errors?._form && (
            <p className="text-green-600 mb-2 font-medium">{state.message}</p>
          )}
          <Button
            size="lg"
            className="px-10 py-4 text-lg font-bold bg-gradient-to-r from-indigo-500 to-pink-500 text-white shadow-lg hover:scale-105 hover:shadow-2xl transition-transform"
            type="submit"
          >
            Create Agent
          </Button>
        </div>
    </form>
  );
}