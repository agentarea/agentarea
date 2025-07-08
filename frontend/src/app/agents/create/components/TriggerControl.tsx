import { Controller, useWatch } from "react-hook-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { ChevronRight, Edit, Trash2 } from "lucide-react";
import type { AgentFormValues } from "../types";
import { Control } from "react-hook-form";
import { AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion";
import { Switch } from "@/components/ui/switch";
import { cn } from "@/lib/utils";

type TriggerControlProps = {
  trigger: any | undefined;
  index: number;
  name: any;
  enabledName: string;
  control: Control<AgentFormValues>;
  removeEvent?: (index: number) => void;
  editEvent?: (index: number) => void;
}

export const TriggerControl = ({ trigger, index, control, removeEvent, editEvent, name, enabledName }: TriggerControlProps) => {
    if (!trigger) return <div className="mt-1 flex items-center gap-2 text-red-500">Something went wrong with the trigger</div>;

    // Watch enabled value to decide badge style
    const enabled = useWatch({ control, name: enabledName as any }) ?? true;

    return (
        <AccordionItem value={`trigger-${index}`} className="border-none py-1.5">
            <AccordionTrigger
                chevron={<ChevronRight className="h-4 w-4 shrink-0 text-transparent group-hover:text-accent transition-all duration-300" />}
                className="group w-max flex flex-row gap-2 py-0 justify-start rotate-0 hover:no-underline [&[data-state=open]>svg]:rotate-90 [&[data-state=open]>svg]:text-accent"
                controls={
                    <div className="flex flex-row items-center gap-3">
                        <Controller
                            key="switch"
                            name={enabledName as any}
                            control={control}
                            defaultValue={true}
                            render={({ field }) => (
                                <div className="flex items-center gap-1">
                                    <span
                                        className="note cursor-pointer select-none hidden sm:block"
                                        onClick={() => field.onChange(!field.value)}
                                    >
                                        {field.value ? "enabled" : "disabled"}
                                    </span>
                                    <Switch
                                        size="xs"
                                        checked={field.value ?? true}
                                        onCheckedChange={field.onChange}
                                        aria-label="Toggle tool"
                                    />
                                </div>
                            )}
                        />
                        {editEvent && (
                            <Button
                                key="edit"
                                type="button"
                                variant="ghost"
                                size="icon"
                                onClick={() => editEvent(index)}
                                className="text-muted-foreground/60 h-4 w-4 flex-shrink-0 hover:bg-transparent"
                                aria-label="Edit Event"
                            >
                                <Edit className="h-4 w-4" />
                            </Button>
                        )}
                        {removeEvent && (
                            <Button
                                key="remove"
                                type="button"
                                variant="ghost"
                                size="icon"
                                onClick={() => removeEvent(index)}
                                className="text-muted-foreground/60 h-4 w-4 flex-shrink-0 hover:bg-transparent"
                                aria-label="Remove Event"
                            >
                                <Trash2 className="h-4 w-4" />
                            </Button>
                        )}
                    </div>
                }
            >
                <Controller
                    name={name as any}
                    control={control}
                    rules={{ required: "Event type is required" }}
                    render={({ field }) => (
                        <Badge 
                            variant={enabled ? 'default' : 'disabled'} 
                            className={cn(
                                "flex items-center gap-2 border border-transparent", 
                                enabled && "group-hover:border-accent", 
                                !enabled && "group-hover:border-zinc-400"
                            )}
                            onClick={() => {
                                if (enabled) {
                                    field.onChange(false);
                                }
                            }}>
                                <div className="w-4 h-4 min-w-4">{trigger.icon}</div>
                                {/* TODO: FIX THIS */}
                                <div>{trigger.label || trigger.name}</div> 
                        </Badge>
                    )}
                />
            </AccordionTrigger>
            <AccordionContent className="px-4 ">
                {/* TODO: test form! FIX THIS */}
                <div className="mt-2 gap-2 p-3 border rounded-md text-muted-foreground/50 text-xs cursor-default">
                    SOME INFO HERE SOME INFO HERE SOME INFO HERE SOME INFO HERE 
                    <br />
                    <br />
                    - some info here
                    <br />
                    - some info here
                </div>
            </AccordionContent>
        </AccordionItem>
    );
};