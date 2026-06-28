"use client";

import type { AgentResponse, McpServerInstanceResponse, McpServerResponse, ModelInstanceResponse } from "@/api/client/types.gen";
import React, { useActionState, useEffect, useState } from "react";
import { useFieldArray, useForm } from "react-hook-form";
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
import SkillsSection from "./components/SkillsSection";
import type { Skill } from "@/lib/api";

type MCPServer = McpServerResponse;
type LLMModelInstance = ModelInstanceResponse;
type Agent = AgentResponse;
type MCPInstance = McpServerInstanceResponse;

interface AgentSkill {
  id: string;
  name: string;
  description?: string | null;
}

export default function EditAgentClient({
  agent,
  mcpServers,
  llmModelInstances,
  mcpInstanceList,
  builtinTools,
  availableSkills,
}: {
  agent: Agent;
  mcpServers: MCPServer[];
  llmModelInstances: LLMModelInstance[];
  mcpInstanceList: MCPInstance[];
  builtinTools: any[];
  availableSkills: Skill[];
}) {
  const [state, formAction] = useActionState(updateAgent, agentInitialState);

  // Skills state (managed separately from react-hook-form for simplicity)
  // Note: agent.skills comes from the API but TypeScript schema may not include it yet
  const [selectedSkills, setSelectedSkills] = useState<AgentSkill[]>(
    ((agent as any).skills || []).map((s: any) => ({
      id: s.id,
      name: s.name,
      description: s.description,
    }))
  );

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
      tools_config: (agent as any).tools_config || { mcp_server_configs: [] },
      events_config: (agent as any).events_config || { events: [] },
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
    formAction({
      ...data,
      id: agent.id,
      skill_ids: selectedSkills.map((skill) => skill.id),
    });
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
            <div className="my-6 h-[1px] w-full bg-slate-200" />
            <div className="px-6 pb-4">
              <SkillsSection
                selectedSkills={selectedSkills}
                onSkillsChange={setSelectedSkills}
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
