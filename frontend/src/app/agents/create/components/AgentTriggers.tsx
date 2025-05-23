import React, { useEffect, useState } from "react";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Trash2, Calendar, MessageSquare, Wand2, Zap } from "lucide-react";
import { Controller, FieldErrors, UseFieldArrayReturn, Control } from 'react-hook-form';
import AccordionControl from "./AccordionControl";
import { getNestedErrorMessage } from "../utils/formUtils";
import type { AgentFormValues, EventConfig } from "../types";
import { Badge } from "@/components/ui/badge";

// Define event trigger types
const eventOptions = [
  { id: 'text_input', label: 'Text Input', description: 'Agent responds when a user sends a text message', icon: <MessageSquare className="h-4 w-4 mr-2" /> },
  { id: 'agent_call', label: 'Agent Call', description: 'Agent is triggered when called by another agent', icon: <Wand2 className="h-4 w-4 mr-2" /> },
  { id: 'cron', label: 'Scheduled (Cron)', description: 'Agent runs on a regular schedule', icon: <Calendar className="h-4 w-4 mr-2" /> },
];

type AgentTriggersProps = {
  control: Control<AgentFormValues>;
  errors: FieldErrors<AgentFormValues>;
  eventFields: UseFieldArrayReturn<AgentFormValues, "events_config.events", "id">["fields"];
  removeEvent: (index: number) => void;
  appendEvent: (data: EventConfig) => void;
};

const AgentTriggers = ({ control, errors, eventFields, removeEvent, appendEvent }: AgentTriggersProps) => {
  const [accordionValue, setAccordionValue] = useState<string>("triggers");

  // Add default events if none exist
  useEffect(() => {
    if (eventFields.length === 0) {
      // Add the two default event types
      appendEvent({ event_type: 'text_input' });
      appendEvent({ event_type: 'agent_call' });
    }
  }, []);

  const searchUsers = async (query?: string) => {
    // Simulate API delay
    await new Promise(resolve => setTimeout(resolve, 500));

    if (!query) return eventOptions;

    return eventOptions.filter(item => 
      item.label.toLowerCase().includes(query.toLowerCase()) ||
      item.description.toLowerCase().includes(query.toLowerCase())
    );
  };

  const note = (
    <>
      <p>Triggers determine when your agent is activated to perform its tasks.</p>
      <p>Select when you want your agent to be activated. You can add multiple triggers.</p>
    </>
  );

  const title = (
    <div className="flex items-center gap-2">
      <Zap className="h-5 w-5 text-accent" /> Agent Triggers
    </div>
  );

  return (
    <>
        <AccordionControl 
          id="triggers" 
          accordionValue={accordionValue} 
          setAccordionValue={setAccordionValue} 
          onAdd={(id: string) => {
            appendEvent({ event_type: id });
            setAccordionValue("triggers");
          }}
          dropdownItems={eventOptions}
          title={title}
          note={note}
          addText="Trigger"
        >
          <div className="space-y-3">
          {eventFields.length > 0 ? eventFields.map((item, index) => (
            <div 
                key={item.id} 
                className="mt-2 flex items-center gap-2"
                // className="mt-2 flex items-center gap-2 p-3 border rounded-md bg-primary/10 shadow-sm hover:shadow-md transition-shadow"
            >
              <div className="flex-1">
                <Controller
                  name={`events_config.events.${index}.event_type`}
                  control={control}
                  rules={{ required: "Event type is required" }}
                  render={({ field }) => (
                    // <Select onValueChange={field.onChange} value={field.value ?? ''}>
                    //   <SelectTrigger>
                    //     <SelectValue placeholder="Select a trigger type" />
                    //   </SelectTrigger>
                    //   <SelectContent>
                    //     {eventOptions.map((option) => (
                    //       <SelectItem key={option.id} value={option.id} className="flex items-center">
                    //         <div className="flex items-center">
                    //           {option.icon}
                    //           <div>
                    //             <div>{option.label}</div>
                    //             <div className="text-xs text-muted-foreground">{option.description}</div>
                    //           </div>
                    //         </div>
                    //       </SelectItem>
                    //     ))}
                    //   </SelectContent>
                    // </Select>
                    <Badge className="flex items-center gap-2">
                      {item.event_type}
                    </Badge>
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
          )) : (
            <div className="mt-2 items-center gap-2 p-3 border rounded-md text-muted-foreground/50 text-xs text-center">
              {note}
            </div>
          )}
        </div>

        </AccordionControl>

        {
          getNestedErrorMessage(errors, 'events_config.events') && 
          <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'events_config.events')}</p>
        }
    </>
  );
};

export default AgentTriggers; 