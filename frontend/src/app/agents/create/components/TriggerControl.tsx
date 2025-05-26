import { Controller } from "react-hook-form";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Edit, Trash2 } from "lucide-react";
import type { AgentFormValues } from "../types";
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { Control } from "react-hook-form";
import { AccordionItem, AccordionTrigger, AccordionContent } from "@/components/ui/accordion";

type TriggerControlProps = {
  trigger: any | undefined;
  index: number;
  name: any;
  control: Control<AgentFormValues>;
  removeEvent: (index: number) => void;
}

export const TriggerControl = ({ trigger, index, control, removeEvent, name }: TriggerControlProps) => {
    if (!trigger) return <div className="mt-1 flex items-center gap-2 text-red-500">Something went wrong with the trigger</div>;

    return (
        <AccordionItem value={`trigger-${index}`} className="border-none">
            <AccordionTrigger
                chevron={<Edit className="h-4 w-4 shrink-0 text-transparent group-hover:text-accent transition-colors duration-300" />}
                className="group w-max flex flex-row gap-2 py-0 justify-start hover:no-underline [&[data-state=open]>svg]:rotate-0 [&[data-state=open]>svg]:text-accent"
                controls={
                    <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        onClick={() => removeEvent(index)}
                        className="text-muted-foreground/60 hover:text-red-500 h-9 w-9 flex-shrink-0 hover:bg-transparent"
                        aria-label="Remove Event"
                    >
                        <Trash2 className="h-4 w-4" />
                    </Button>
                }
            >
                <Controller
                    name={name}
                    control={control}
                    rules={{ required: "Event type is required" }}
                    render={({ field }) => (
                        <Badge className="flex items-center gap-2 border border-transparent group-hover:border-accent">
                            <div className="w-4 h-4 min-w-4">{trigger.icon}</div>
                            {/* TODO: FIX THIS */}
                            <div>{trigger.label || trigger.name}</div> 
                        </Badge>
                    )}
                />
            </AccordionTrigger>
            <AccordionContent className="px-4 ">
                {/* TODO: test form! FIX THIS */}
                <Label htmlFor="name" className="text-sm font-medium">IT IS TEST FIELD</Label>
                <Input
                    type="text"
                    placeholder="Event name"
                    className="w-full"
                />
            </AccordionContent>
        </AccordionItem>
    );
};