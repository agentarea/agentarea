import { Controller } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Edit, Trash2 } from "lucide-react";
import type { AgentFormValues } from "../types";
import { Control } from "react-hook-form";
import { CardAccordionItem } from "@/components/CardAccordionItem";
import { Switch } from "@/components/ui/switch";

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

    const controls = (
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
    );

    return (
        <CardAccordionItem
            value={`trigger-${index}`}
            controls={controls}
            title={trigger.name}
            iconSrc="/Icon.svg" // TODO: replace with real icon
        >
            {/* TODO: test form! FIX THIS */}
            <div className="mt-2 gap-2 p-3 border rounded-md text-muted-foreground/50 text-xs cursor-default">
                SOME INFO HERE SOME INFO HERE SOME INFO HERE SOME INFO HERE
                <br />
                <br />
                - some info here
                <br />
                - some info here
            </div>
        </CardAccordionItem>
    );
};