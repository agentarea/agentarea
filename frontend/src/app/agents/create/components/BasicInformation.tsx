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

type LLMModelInstance = components["schemas"]["LLMModelInstanceResponse"];

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
        <Label htmlFor="name" className="label">
            <Bot className="label-icon" style={{ strokeWidth: 1.5 }} />Agent Name
        </Label>
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
        <Label htmlFor="description" className="label">
          <FileText className="label-icon" style={{ strokeWidth: 1.5 }} /> Description / Goal <span className="text-xs font-light text-zinc-400">(Optional)</span>
        </Label>
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
        <Label htmlFor="instruction" className="label">
          <MessageSquare className="label-icon" style={{ strokeWidth: 1.5 }} /> Instruction <span className="text-sm text-red-500">*</span>
        </Label>
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
        <Label htmlFor="model_id" className="label">
          <Cpu className="label-icon" style={{ strokeWidth: 1.5 }} /> LLM Model
        </Label>
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
                        {instance.name}
                      </SelectItem>
                    ))
                  ) : (
                    <SelectItem value="null" disabled>
                      No LLM models configured. Please add models in Admin → LLMs
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