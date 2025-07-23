import React from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Bot, FileText, MessageSquare, Cpu } from "lucide-react";
import { Controller, FieldErrors, UseFormRegister } from 'react-hook-form';
import { getNestedErrorMessage } from "../utils/formUtils";
import type { AgentFormValues } from "../../create/types";
import type { components } from '@/api/schema';
import FormLabel from "@/components/FormLabel/FormLabel";

type LLMModelInstance = components["schemas"]["ModelInstanceResponse"];

type BasicInformationProps = {
  register: UseFormRegister<AgentFormValues>;
  control: any;
  errors: FieldErrors<AgentFormValues>;
  llmModelInstances: LLMModelInstance[];
};

const BasicInformation = ({ register, control, errors, llmModelInstances }: BasicInformationProps) => (
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
              <Select onValueChange={field.onChange} value={field.value ?? ''}>
                <SelectTrigger>
                  <SelectValue placeholder="Select a model" />
                </SelectTrigger>
                <SelectContent>
                  {llmModelInstances.length > 0 ? (
                    llmModelInstances.map((instance) => (
                      <SelectItem key={instance.id} value={instance.id}>
                        <div className="flex flex-col">
                          <span className="font-medium">{instance.name}</span>
                          <span className="text-xs text-muted-foreground">
                            {instance.provider_name} - {instance.model_display_name}
                          </span>
                        </div>
                      </SelectItem>
                    ))
                  ) : (
                    <SelectItem value="null" disabled>
                      No LLM models configured. Please add models in Admin → Model Instances
                    </SelectItem>
                  )}
                </SelectContent>
              </Select>
            )}
          />
        {getNestedErrorMessage(errors, 'model_id') && <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'model_id')}</p>}
      </div>
    </div>
  </Card>
);

export default BasicInformation; 