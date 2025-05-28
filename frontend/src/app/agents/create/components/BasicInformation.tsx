import React from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sparkles, Bot, FileText, MessageSquare, Cpu } from "lucide-react";
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
  <Card className="">
    {/* <h2 className="mb-6 flex items-center gap-2">
      <Sparkles className="h-5 w-5 text-accent" /> Basic Information
    </h2> */}
    <div className="grid grid-cols-1 gap-6">
      <div className="space-y-2">
        <Label htmlFor="name" className="flex items-center gap-2">
            <Bot className="h-5 w-5 text-primary" style={{ strokeWidth: 1.5 }} />Agent Name
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
        <Label htmlFor="description" className="flex items-center gap-2">
          <FileText className="h-5 w-5 text-primary" style={{ strokeWidth: 1.5 }} /> Description / Goal <span className="text-xs font-light text-zinc-400">(Optional)</span>
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
        <Label htmlFor="instruction" className="flex items-center gap-2">
          <MessageSquare className="h-5 w-5 text-primary" style={{ strokeWidth: 1.5 }} /> Instruction <span className="text-sm text-red-500">*</span>
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
        <Label htmlFor="model_id" className="flex items-center gap-2">
          <Cpu className="h-5 w-5 text-primary" style={{ strokeWidth: 1.5 }} /> LLM Model
        </Label>
         <Controller
            name="model_id"
            control={control}
            rules={{ required: "Model is required" }}
            render={({ field }) => (
              <Select onValueChange={field.onChange} value={field.value ?? ''}>
                <SelectTrigger className="bg-white h-10 w-full rounded-md border border-input px-3 py-2 text-sm file:border-0 file:bg-transparent file:text-sm file:font-medium placeholder:text-muted-foreground outline-none ring-0 focus:outline-none focus:ring-0 focus-visible:outline-none focus-visible:ring-0 focus-visible:ring-offset-0 focus:border-primary disabled:cursor-not-allowed disabled:opacity-50 transition-all duration-300 dark:bg-zinc-900 focus-visible:dark:border-zinc-700">
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