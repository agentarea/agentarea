"use client";

import React, { useActionState, useEffect } from "react";
import { useFieldArray, useForm } from "react-hook-form";
import type { components } from "@/api/schema";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
  AgentTriggers,
  BasicInformation,
  ToolConfig,
} from "../../create/components";
import { initialState as agentInitialState } from "../../create/types";
import type { AgentFormValues, EventConfig } from "../../create/types";
import { updateAgent } from "./actions";

type MCPServer = components["schemas"]["MCPServerResponse"];
type LLMModelInstance = components["schemas"]["ModelInstanceResponse"];
type Agent =
  components["schemas"]["agentarea_api__api__v1__agents__AgentResponse"];
type MCPInstance = components["schemas"]["MCPServerInstanceResponse"];

export default function EditAgentClient({
  agent,
  mcpServers,
  llmModelInstances,
  mcpInstanceList,
  builtinTools,
}: {
  agent: Agent;
  mcpServers: MCPServer[];
  llmModelInstances: LLMModelInstance[];
  mcpInstanceList: MCPInstance[];
  builtinTools: any[];
}) {
  const [state, formAction] = useActionState(updateAgent, agentInitialState);

  const {
    register,
    control,
    setValue,
    handleSubmit,
    formState: { errors },
  } = useForm<AgentFormValues>({
    defaultValues: {
      name: agent.name,
      description: agent.description || "",
      instruction: agent.instruction || "",
      model_id: agent.model_id || "",
      tools_config: agent.tools_config || { mcp_server_configs: [] },
      events_config: agent.events_config || { events: [] },
      planning: agent.planning || false,
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

  useEffect(() => {
    if (state?.fieldValues) {
      setValue("name", state.fieldValues.name ?? "");
      setValue("description", state.fieldValues.description ?? "");
      setValue("instruction", state.fieldValues.instruction ?? "");
      setValue("model_id", state.fieldValues.model_id ?? "");

      if (Array.isArray(state.fieldValues.events_config?.events)) {
        setValue(
          "events_config.events",
          state.fieldValues.events_config.events as unknown as EventConfig[]
        );
      }

      if (Array.isArray(state.fieldValues.tools_config?.mcp_server_configs)) {
        const configs = state.fieldValues.tools_config.mcp_server_configs.map(
          (config) => ({
            mcp_server_id: config.mcp_server_id,
            allowed_tools: config.allowed_tools || [],
          })
        );
        setValue("tools_config.mcp_server_configs", configs);
      }

      setValue("planning", !!state.fieldValues.planning);
    }
  }, [state?.fieldValues, setValue]);

  // Handle form submission with react-hook-form validation
  const onSubmit = (data: AgentFormValues) => {
    // Create FormData for server action
    const formData = new FormData();
    formData.append("id", agent.id);
    formData.append("name", data.name);
    formData.append("description", data.description || "");
    formData.append("instruction", data.instruction);
    formData.append("model_id", data.model_id);
    formData.append("planning", data.planning.toString());

    // Add tools config
    data.tools_config.mcp_server_configs.forEach((config, index) => {
      formData.append(
        `tools_config.mcp_server_configs[${index}].mcp_server_id`,
        config.mcp_server_id
      );
      if (config.allowed_tools) {
        config.allowed_tools.forEach((tool, toolIndex) => {
          formData.append(
            `tools_config.mcp_server_configs[${index}].allowed_tools[${toolIndex}].tool_name`,
            tool.tool_name
          );
          formData.append(
            `tools_config.mcp_server_configs[${index}].allowed_tools[${toolIndex}].requires_user_confirmation`,
            (tool.requires_user_confirmation ?? false).toString()
          );
        });
      }
    });

    // Add events config
    data.events_config.events.forEach((event, index) => {
      formData.append(
        `events_config.events[${index}].event_type`,
        event.event_type
      );
      if (event.config) {
        formData.append(
          `events_config.events[${index}].config`,
          JSON.stringify(event.config)
        );
      }
      formData.append(
        `events_config.events[${index}].enabled`,
        (event.enabled ?? true).toString()
      );
    });

    // Call server action
    formAction(formData);
  };

  return (
    <form onSubmit={handleSubmit(onSubmit)}>
      <div className="mx-auto grid max-w-6xl grid-cols-1 items-start gap-[12px] lg:grid-cols-2 lg:gap-x-[12px]">
        <div className="">
          <BasicInformation
            register={register}
            control={control}
            errors={errors}
            setValue={setValue}
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

      <div className="sticky bottom-0 z-10 -mx-4 mx-auto flex max-w-6xl flex-row items-end justify-end gap-4 px-4 pb-2 pt-6">
        {state?.errors?._form && (
          <p className="mb-2 form-error">
            {state.errors._form.join(", ")}
          </p>
        )}
        {state?.message && !state.errors?._form && (
          <p className="mb-2 text-sm text-green-600">{state.message}</p>
        )}
        <Button size="lg" className="" type="submit">
          Update Agent
        </Button>
      </div>
    </form>
  );
}
