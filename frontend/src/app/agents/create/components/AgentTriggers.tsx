import React, { useEffect } from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Plus, Trash2, HelpCircle, Calendar, MessageSquare, Wand2 } from "lucide-react";
import { Controller, FieldErrors, UseFieldArrayReturn, Control } from 'react-hook-form';
import { getNestedErrorMessage } from "../utils/formUtils";
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from "@/components/ui/tooltip";

// Define event trigger types
const eventOptions = [
  { id: 'text_input', label: 'Text Input', description: 'Agent responds when a user sends a text message', icon: <MessageSquare className="h-4 w-4 mr-2" /> },
  { id: 'agent_call', label: 'Agent Call', description: 'Agent is triggered when called by another agent', icon: <Wand2 className="h-4 w-4 mr-2" /> },
  { id: 'cron', label: 'Scheduled (Cron)', description: 'Agent runs on a regular schedule', icon: <Calendar className="h-4 w-4 mr-2" /> },
];

// Define simplified event config type
export interface EventConfig {
  event_type: string;
}

// Define form values type if not already defined in types.ts
export interface AgentFormValues {
  events_config: {
    events: EventConfig[];
  };
  // Other form fields would go here
}

type AgentTriggersProps = {
  control: Control<AgentFormValues>;
  errors: FieldErrors<AgentFormValues>;
  eventFields: UseFieldArrayReturn<AgentFormValues, "events_config.events", "id">["fields"];
  removeEvent: (index: number) => void;
  appendEvent: (data: EventConfig) => void;
};

const AgentTriggers = ({ control, errors, eventFields, removeEvent, appendEvent }: AgentTriggersProps) => {
  // Add default events if none exist
  useEffect(() => {
    if (eventFields.length === 0) {
      // Add the two default event types
      appendEvent({ event_type: 'text_input' });
      appendEvent({ event_type: 'agent_call' });
    }
  }, []);

  return (
    <Card className="p-6 shadow-xl border-0 bg-white/90 hover:shadow-2xl transition-shadow">
      <div className="flex items-center mb-4">
        <h2 className="text-2xl font-bold">Agent Triggers</h2>
        <TooltipProvider>
          <Tooltip delayDuration={300}>
            <TooltipTrigger asChild>
              <Button variant="ghost" size="icon" className="ml-2 h-6 w-6 text-muted-foreground hover:text-primary">
                <HelpCircle className="h-4 w-4" />
              </Button>
            </TooltipTrigger>
            <TooltipContent className="max-w-xs">
              <p>Triggers determine when your agent is activated to perform its tasks.</p>
            </TooltipContent>
          </Tooltip>
        </TooltipProvider>
      </div>
      
      <div className="text-sm text-muted-foreground mb-4">
        Select when you want your agent to be activated. You can add multiple triggers.
      </div>

      <div className="space-y-4">
        <div className="space-y-3">
          {eventFields.map((item, index) => (
            <div key={item.id} className="flex items-center gap-2 p-3 border rounded-md bg-slate-50 shadow-sm hover:shadow-md transition-shadow">
              <div className="flex-1">
                <Controller
                  name={`events_config.events.${index}.event_type`}
                  control={control}
                  rules={{ required: "Event type is required" }}
                  render={({ field }) => (
                    <Select onValueChange={field.onChange} value={field.value ?? ''}>
                      <SelectTrigger>
                        <SelectValue placeholder="Select a trigger type" />
                      </SelectTrigger>
                      <SelectContent>
                        {eventOptions.map((option) => (
                          <SelectItem key={option.id} value={option.id} className="flex items-center">
                            <div className="flex items-center">
                              {option.icon}
                              <div>
                                <div>{option.label}</div>
                                <div className="text-xs text-muted-foreground">{option.description}</div>
                              </div>
                            </div>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
                />
              </div>
              
              <Button
                type="button"
                variant="ghost"
                size="icon"
                onClick={() => removeEvent(index)}
                className="text-muted-foreground hover:text-red-500 h-9 w-9 flex-shrink-0"
                aria-label="Remove Event"
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </div>
          ))}
        </div>
        
        <Button 
          type="button" 
          variant="outline" 
          onClick={() => appendEvent({ event_type: 'text_input' })}
          className="group w-full border-dashed border-gray-300 hover:border-primary hover:bg-primary/5"
        >
          <Plus className="h-4 w-4 mr-2 group-hover:text-primary" /> Add Another Trigger
        </Button>
        
        {getNestedErrorMessage(errors, 'events_config.events') && 
        <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'events_config.events')}</p>}
      </div>
    </Card>
  );
};

export default AgentTriggers; 