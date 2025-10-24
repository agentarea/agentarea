import React, { useState, useEffect, useMemo } from "react";
import { Wand2, Zap, Clock } from "lucide-react";
import { FieldErrors, UseFieldArrayReturn, Control } from 'react-hook-form';
import AccordionControl from "./AccordionControl";
import { getNestedErrorMessage } from "../utils/formUtils";
import type { AgentFormValues, EventConfig } from "../types";
import { TriggerControl } from "./TriggerControl";
import { Accordion } from "@/components/ui/accordion";
import { SelectableList } from "./SelectableList";
import FormLabel from "@/components/FormLabel/FormLabel";
import ConfigSheet from "./ConfigSheet";
import { useTranslations } from "next-intl";

// Icon components
const TelegramIcon = ({ className }: { className?: string }) => (
  <svg viewBox="0 0 240.1 240.1" className={className}>
    <linearGradient id="Oval_1_" gradientUnits="userSpaceOnUse" x1="-838.041" y1="660.581" x2="-838.041" y2="660.3427" gradientTransform="matrix(1000 0 0 -1000 838161 660581)">
      <stop offset="0" stopColor="#2AABEE"/>
      <stop offset="1" stopColor="#229ED9"/>
    </linearGradient>
    <circle fillRule="evenodd" clipRule="evenodd" fill="url(#Oval_1_)" cx="120.1" cy="120.1" r="120.1"/>
    <path fillRule="evenodd" clipRule="evenodd" fill="#FFFFFF" d="M54.3,118.8c35-15.2,58.3-25.3,70-30.2 c33.3-13.9,40.3-16.3,44.8-16.4c1,0,3.2,0.2,4.7,1.4c1.2,1,1.5,2.3,1.7,3.3s0.4,3.1,0.2,4.7c-1.8,19-9.6,65.1-13.6,86.3 c-1.7,9-5,12-8.2,12.3c-7,0.6-12.3-4.6-19-9c-10.6-6.9-16.5-11.2-26.8-18c-11.9-7.8-4.2-12.1,2.6-19.1c1.8-1.8,32.5-29.8,33.1-32.3 c0.1-0.3,0.1-1.5-0.6-2.1c-0.7-0.6-1.7-0.4-2.5-0.2c-1.1,0.2-17.9,11.4-50.6,33.5c-4.8,3.3-9.1,4.9-13,4.8 c-4.3-0.1-12.5-2.4-18.7-4.4c-7.5-2.4-13.5-3.7-13-7.9C45.7,123.3,48.7,121.1,54.3,118.8z"/>
  </svg>
);

// Define event trigger types
const eventOptions = [
  { id: 'telegram', name: 'telegram', label: 'Telegram', description: '', icon: TelegramIcon },
  { id: 'agent_call', name: 'agent_call', label: 'Agent Call', description: '', icon: Wand2 },
  { id: 'scheduled', name: 'scheduled', label: 'Scheduled', description: '', icon: Clock },
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
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const [scrollTriggerId, setScrollTriggerId] = useState<string | null>(null);
  const t = useTranslations("AgentsPage");

  // Precompute map for quick lookup of trigger option by id
  const triggerMap = useMemo(() => {
    const map: Record<string, typeof eventOptions[number]> = {};
    eventOptions.forEach((o) => {
      map[o.id] = o;
    });
    return map;
  }, []);

  const note = useMemo(() => (
    <>
      <p>{t("create.agentTriggersNote")}</p>
      <p>{t("create.agentTriggersNoteDescription")}</p>
    </>
  ), []);

  const title = useMemo(() => (
    <FormLabel icon={Zap} className="cursor-pointer">{t("create.agentTriggers")}</FormLabel>
  ), []);

  useEffect(()=>{
    if(isSheetOpen && scrollTriggerId){
      const timer=setTimeout(()=>{
        const el=document.getElementById(`trigger-${scrollTriggerId}`);
        el?.scrollIntoView({behavior:'smooth', block:'center'});
      },100);
      return ()=>clearTimeout(timer);
    }
  },[isSheetOpen, scrollTriggerId]);

  return (
    <>
      <AccordionControl
        id="triggers"
        accordionValue={accordionValue}
        setAccordionValue={setAccordionValue}
        title={title}
        note={note}
        mainControl={
          <ConfigSheet
            title={t("create.agentTriggers")}
            description={t("create.agentTriggersDescription")}
            triggerText={t("create.trigger")}
          >
            <SelectableList
              items={eventOptions}
              prefix="trigger"
              extractTitle={(opt) => opt.label}
              onAdd={(opt) => appendEvent({ event_type: opt.id })}
              onRemove={(opt) => {
                const idx = eventFields.findIndex((f) => f.event_type === opt.id);
                if (idx !== -1) removeEvent(idx);
              }}
              selectedIds={eventFields.map((f) => f.event_type)}
              openItemId={scrollTriggerId}
              renderContent={(opt) => (
                <div className="p-4 text-sm text-muted-foreground">{opt.description || "Description"}</div>
              )}
            />
          </ConfigSheet>
        }
      >
        <div className="space-y-1">
          {eventFields.length>0 ? (
            <Accordion type="multiple" id="triggers-items" className="space-y-2">
              {eventFields.map((item,index)=>(
                <TriggerControl
                  key={item.id}
                  trigger={triggerMap[item.event_type]}
                  index={index}
                  control={control}
                  removeEvent={removeEvent}
                  enabledName={`events_config.events.${index}.enabled`}
                  name={`events_config.events.${index}.event_type`}
                  editEvent={()=>{
                    setScrollTriggerId(item.event_type);
                    setIsSheetOpen(true);
                  }}
                />
              ))}
            </Accordion>
          ): (
            <div className="mt-2 items-center gap-2 p-3 border rounded-md text-muted-foreground/50 text-xs text-center cursor-default">
              {note}
            </div>
          )}
        </div>
      </AccordionControl>

      {getNestedErrorMessage(errors,'events_config.events') && (
        <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors,'events_config.events')}</p>
      )}
    </>
  );
};

export default AgentTriggers; 