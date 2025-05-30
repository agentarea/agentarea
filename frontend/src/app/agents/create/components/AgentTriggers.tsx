import React, { useState } from "react";
import { Wand2, Zap, Clock } from "lucide-react";
import { FieldErrors, UseFieldArrayReturn, Control } from 'react-hook-form';
import AccordionControl from "./AccordionControl";
import { getNestedErrorMessage } from "../utils/formUtils";
import type { AgentFormValues, EventConfig } from "../types";
import { TriggerControl } from "./TriggerControl";
import { Accordion } from "@/components/ui/accordion";

// Define event trigger types
const eventOptions = [
  { id: 'telegram', label: 'Telegram', description: '', icon: (
    <svg viewBox="0 0 240.1 240.1">
      <linearGradient id="Oval_1_" gradientUnits="userSpaceOnUse" x1="-838.041" y1="660.581" x2="-838.041" y2="660.3427" gradientTransform="matrix(1000 0 0 -1000 838161 660581)">
        <stop offset="0" stopColor="#2AABEE"/>
        <stop offset="1" stopColor="#229ED9"/>
      </linearGradient>
      <circle fillRule="evenodd" clipRule="evenodd" fill="url(#Oval_1_)" cx="120.1" cy="120.1" r="120.1"/>
      <path fillRule="evenodd" clipRule="evenodd" fill="#FFFFFF" d="M54.3,118.8c35-15.2,58.3-25.3,70-30.2 c33.3-13.9,40.3-16.3,44.8-16.4c1,0,3.2,0.2,4.7,1.4c1.2,1,1.5,2.3,1.7,3.3s0.4,3.1,0.2,4.7c-1.8,19-9.6,65.1-13.6,86.3 c-1.7,9-5,12-8.2,12.3c-7,0.6-12.3-4.6-19-9c-10.6-6.9-16.5-11.2-26.8-18c-11.9-7.8-4.2-12.1,2.6-19.1c1.8-1.8,32.5-29.8,33.1-32.3 c0.1-0.3,0.1-1.5-0.6-2.1c-0.7-0.6-1.7-0.4-2.5-0.2c-1.1,0.2-17.9,11.4-50.6,33.5c-4.8,3.3-9.1,4.9-13,4.8 c-4.3-0.1-12.5-2.4-18.7-4.4c-7.5-2.4-13.5-3.7-13-7.9C45.7,123.3,48.7,121.1,54.3,118.8z"/>
    </svg>
  ) },
  { id: 'agent_call', label: 'Agent Call', description: '', icon: <Wand2 className="h-4 w-4 mr-2" /> },
  { id: 'scheduled', label: 'Scheduled', description: '', icon: <Clock className="h-4 w-4 mr-2" /> },
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

  // // Add default events if none exist
  // useEffect(() => {
  //   if (eventFields.length === 0) {
  //     // Add the two default event types
  //     appendEvent({ event_type: 'text_input' });
  //     appendEvent({ event_type: 'agent_call' });
  //   }
  // }, []);

  // const searchUsers = async (query?: string) => {
  //   // Simulate API delay
  //   await new Promise(resolve => setTimeout(resolve, 500));

  //   if (!query) return eventOptions;

  //   return eventOptions.filter(item => 
  //     item.label.toLowerCase().includes(query.toLowerCase()) ||
  //     item.description.toLowerCase().includes(query.toLowerCase())
  //   );
  // };

  const note = (
    <>
      <p>Triggers determine when your agent is activated to perform its tasks.</p>
      <p>Select when you want your agent to be activated. You can add multiple triggers.</p>
    </>
  );

  const title = (
    <div className="flex items-center gap-2">
      <Zap className="label-icon" style={{ strokeWidth: 1.5 }} /> Agent Triggers
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
          {/*  */}
          <div className="space-y-1">
          {eventFields.length > 0 ? (
              <Accordion type="multiple" id="triggers-items">
                {
                  eventFields.map((item, index) => (
                    <TriggerControl 
                      key={`trigger-${index}`}
                      trigger={eventOptions.find(option => option.id === item.event_type) || undefined} 
                      index={index} 
                      control={control} 
                      removeEvent={removeEvent}
                      name={`events_config.events.${index}.event_type`}
                    />
                  ))
                }
              </Accordion>
            ) : (
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