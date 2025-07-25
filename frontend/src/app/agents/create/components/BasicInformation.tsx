import React, { useState, useRef } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { SearchableSelect } from "@/components/ui/searchable-select";
import { Bot, FileText, MessageSquare, Cpu, Brain } from "lucide-react";
import { Controller, FieldErrors, UseFormRegister } from 'react-hook-form';
import { getNestedErrorMessage } from "../utils/formUtils";
import type { AgentFormValues } from "../../create/types";
import type { components } from '@/api/schema';
import FormLabel from "@/components/FormLabel/FormLabel";
import { Button } from "@/components/ui/button";
import ConfigSheet from "./ConfigSheet";

type LLMModelInstance = components["schemas"]["ModelInstanceResponse"];

type BasicInformationProps = {
  register: UseFormRegister<AgentFormValues>;
  control: any;
  errors: FieldErrors<AgentFormValues>;
  llmModelInstances: LLMModelInstance[];
  onOpenConfigSheet: () => void;
};

const BasicInformation = ({ register, control, errors, llmModelInstances, onOpenConfigSheet }: BasicInformationProps) => {
  const [searchableSelectOpen, setSearchableSelectOpen] = useState(false);
  const configSheetTriggerRef = useRef<HTMLButtonElement>(null);

  const handleConfigSheetOpenChange = (open: boolean) => {
    if (open) {
      // Close SearchableSelect when ConfigSheet opens
      setSearchableSelectOpen(false);
    }
  };

  const handleCreateConfigClick = () => {
    // Programmatically click the ConfigSheet trigger button
    configSheetTriggerRef.current?.click();
    setSearchableSelectOpen(false);
  };

  return (
    <Card className="">
      {/* <h2 className="mb-6 label">
        <Sparkles className="h-5 w-5 text-accent" /> Basic Information
      </h2> */}
      <div className="grid grid-cols-1 gap-6">
        <div className="space-y-2">
          <FormLabel htmlFor="name" icon={Bot}>Agent Name</FormLabel>
          <Input
            id="name"
            {...register('name', { required: "Agent name is required" })}
            placeholder="Enter agent name"
            // className="mt-2 text-lg px-4 py-3 border-2 border-slate-200 focus:border-indigo-400 transition-colors"
            aria-invalid={!!getNestedErrorMessage(errors, 'name')}
          />
          {getNestedErrorMessage(errors, 'name') && <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'name')}</p>}
        </div>
        <div className="space-y-2">
          <FormLabel htmlFor="description" icon={FileText} optional>Description / Goal</FormLabel>
          <Textarea
            id="description"
            {...register('description')}
            placeholder="Describe the agent's purpose, personality, and main goal..."
            className="resize-none h-[100px]"
            // className="mt-2 text-base px-4 py-3 border-2 border-slate-200 focus:border-indigo-400 transition-colors h-32"
            aria-invalid={!!getNestedErrorMessage(errors, 'description')}
          />
          {getNestedErrorMessage(errors, 'description') && <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'description')}</p>}
        </div>
        <div className="space-y-2">
          <FormLabel htmlFor="instruction" icon={MessageSquare} required>Instruction</FormLabel>
          <Textarea
            id="instruction"
            {...register('instruction', { required: "Instruction is required" })}
            placeholder="Provide specific instructions for this agent..."
            className="resize-none h-[100px]"
            // className="mt-2 text-base px-4 py-3 border-2 border-slate-200 focus:border-indigo-400 transition-colors h-32"
            aria-invalid={!!getNestedErrorMessage(errors, 'instruction')}
          />
          {getNestedErrorMessage(errors, 'instruction') && <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'instruction')}</p>}
        </div>
        <div className="space-y-2">
          <FormLabel htmlFor="model_id" icon={Cpu}>LLM Model</FormLabel>
           <Controller
              name="model_id"
              control={control}
              rules={{ required: "Model is required" }}
              render={({ field }) => (
                <SearchableSelect
                  options={llmModelInstances.length > 0 ? 
                    llmModelInstances.map((instance) => ({
                      id: instance.id,
                      label: instance.name,
                      description: `${instance.provider_name} - ${instance.model_display_name}`,
                    })) : []
                  }
                  value={field.value}
                  onValueChange={field.onChange}
                  placeholder="Select a model"
                  open={searchableSelectOpen}
                  onOpenChange={setSearchableSelectOpen}
                  emptyMessage={
                    <div className="flex flex-col items-center gap-2 px-6">
                      <div>No configurations yet</div>
                      <div className="note">Create and use a provider configuration</div>
                      <Button 
                        size="sm" 
                        onClick={handleCreateConfigClick}
                        className="mt-2"
                      >
                        Create Configuration
                      </Button>
                    </div>
                  }
                  defaultIcon={<Brain className="w-5 h-5" />}
                />
              )}
            />
          {getNestedErrorMessage(errors, 'model_id') && <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'model_id')}</p>}
        </div>
      </div>

      {/* ConfigSheet rendered outside of SearchableSelect */}
      <ConfigSheet
        title="Create Configuration"
        className="md:min-w-[500px]"
        description=""
        triggerClassName="hidden"
        onOpenChange={handleConfigSheetOpenChange}
        triggerRef={configSheetTriggerRef}
      >
        TEST
      </ConfigSheet>
    </Card>
  );
};

export default BasicInformation; 