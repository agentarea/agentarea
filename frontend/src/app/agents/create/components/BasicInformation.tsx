import React from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sparkles } from "lucide-react";
import { Controller, FieldErrors, UseFormRegister } from 'react-hook-form';
import { getNestedErrorMessage } from "../utils/formUtils";
import type { AgentFormValues } from "../../create/types";

const availableLLMs = [
  { id: "gpt-4", name: "GPT-4" },
  { id: "gpt-3.5-turbo", name: "GPT-3.5 Turbo" },
  { id: "claude-3", name: "Claude 3" },
];

type BasicInformationProps = {
  register: UseFormRegister<AgentFormValues>;
  control: any;
  errors: FieldErrors<AgentFormValues>;
};

const BasicInformation = ({ register, control, errors }: BasicInformationProps) => (
  <Card className="p-8 shadow-xl border-0 bg-white/90 hover:shadow-2xl transition-shadow">
    <h2 className="text-2xl font-bold mb-6 flex items-center gap-2">
      <Sparkles className="h-5 w-5 text-purple-500" /> Basic Information
    </h2>
    <div className="grid grid-cols-1 gap-6">
      <div>
        <Label htmlFor="name" className="text-base font-medium">Agent Name</Label>
        <Input
          id="name"
          {...register('name', { required: "Agent name is required" })}
          placeholder="Enter agent name"
          className="mt-2 text-lg px-4 py-3 border-2 border-slate-200 focus:border-indigo-400 transition-colors"
          aria-invalid={!!getNestedErrorMessage(errors, 'name')}
        />
        {getNestedErrorMessage(errors, 'name') && <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'name')}</p>}
      </div>
      <div>
        <Label htmlFor="description" className="text-base font-medium">Description / Goal <span className="text-sm text-slate-500">(Optional)</span></Label>
        <Textarea
          id="description"
          {...register('description')}
          placeholder="Describe the agent's purpose, personality, and main goal..."
          className="mt-2 text-base px-4 py-3 border-2 border-slate-200 focus:border-indigo-400 transition-colors h-32"
          aria-invalid={!!getNestedErrorMessage(errors, 'description')}
        />
        {getNestedErrorMessage(errors, 'description') && <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'description')}</p>}
      </div>
      <div>
        <Label htmlFor="instruction" className="text-base font-medium">Instruction <span className="text-sm text-red-500">*</span></Label>
        <Textarea
          id="instruction"
          {...register('instruction', { required: "Instruction is required" })}
          placeholder="Provide specific instructions for this agent..."
          className="mt-2 text-base px-4 py-3 border-2 border-slate-200 focus:border-indigo-400 transition-colors h-32"
          aria-invalid={!!getNestedErrorMessage(errors, 'instruction')}
        />
        {getNestedErrorMessage(errors, 'instruction') && <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'instruction')}</p>}
      </div>
      <div>
        <Label htmlFor="model_id" className="text-base font-medium">LLM Model</Label>
         <Controller
            name="model_id"
            control={control}
            rules={{ required: "Model is required" }}
            render={({ field }) => (
              <Select onValueChange={field.onChange} value={field.value ?? ''}>
                <SelectTrigger className="mt-2 text-lg px-4 py-3 border-2 border-slate-200 focus:border-indigo-400 transition-colors">
                  <SelectValue placeholder="Select a model" />
                </SelectTrigger>
                <SelectContent>
                  {availableLLMs.map((llm) => (
                    <SelectItem key={llm.id} value={llm.id}>{llm.name}</SelectItem>
                  ))}
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