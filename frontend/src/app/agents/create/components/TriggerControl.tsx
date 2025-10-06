import { Controller } from "react-hook-form";
import { Button } from "@/components/ui/button";
import { Edit, Trash2, LucideIcon } from "lucide-react";
import type { AgentFormValues } from "../types";
import { Control } from "react-hook-form";
import { CardAccordionItem } from "@/components/CardAccordionItem/CardAccordionItem";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";

type TriggerControlProps = {
  trigger: any | undefined;
  index: number;
  name: any;
  enabledName: string;
  control: Control<AgentFormValues>;
  removeEvent?: (index: number) => void;
  editEvent?: (index: number) => void;
  selectedMethods?: Record<string, boolean>;
  onMethodToggle?: (methodName: string, checked: boolean) => void;
}

export const TriggerControl = ({ trigger, index, control, removeEvent, editEvent, name, enabledName, selectedMethods = {}, onMethodToggle }: TriggerControlProps) => {
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
                    className="text-muted-foreground/60 h-4 w-4 flex-shrink-0 hover:bg-transparent hover:text-primary"
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
                    className="text-muted-foreground/60 h-4 w-4 flex-shrink-0 hover:bg-transparent hover:text-red-500"
                    aria-label="Remove Event"
                >
                    <Trash2 className="h-4 w-4" />
                </Button>
            )}
        </div>
    );

    // Create custom title with icon if provided
    const titleNode = trigger.icon ? (
        <div className="flex flex-row items-center gap-2 px-[7px] py-[7px]">
            <trigger.icon className="w-5 h-5 text-muted-foreground" />
            <h3 className="text-sm font-medium transition-colors duration-300 group-hover:text-accent dark:group-hover:text-accent group-data-[state=open]:text-accent dark:group-data-[state=open]:text-accent">
                {trigger.label || trigger.name}
            </h3>
        </div>
    ) : (trigger.label || trigger.name);

    return (
        <CardAccordionItem
            value={`trigger-${index}`}
            controls={controls}
            title={titleNode}
            iconSrc={trigger.icon ? undefined : "/Icon.svg"}
        >
            <div className="mt-2 p-2 space-y-2">
                <p className="text-xs text-muted-foreground">
                    {trigger.description || trigger.label || trigger.name}
                </p>
                {trigger.available_methods && trigger.available_methods.length > 0 && (
                    <div className="space-y-1">
                        <div className="flex items-center justify-between">
                            <p className="text-xs font-medium text-foreground">Available Methods:</p>
                            <span className="text-xs text-muted-foreground bg-muted/50 px-2 py-0.5 rounded-full">
                                {onMethodToggle ? 
                                    `${trigger.available_methods.filter((method: any) => selectedMethods[method.name] !== false).length}/${trigger.available_methods.length}` :
                                    `${trigger.available_methods.length}/${trigger.available_methods.length}`
                                }
                            </span>
                        </div>
                        <div className="space-y-1">
                            {trigger.available_methods.map((method: any) => (
                                <div key={method.name} className="flex items-center gap-2 p-1 rounded bg-muted/30">
                                    {onMethodToggle ? (
                                        <>
                                            <Checkbox
                                                checked={selectedMethods[method.name] !== false}
                                                onCheckedChange={(checked) => 
                                                    onMethodToggle(method.name, checked as boolean)
                                                }
                                                className="h-4 w-4 data-[state=checked]:bg-primary data-[state=checked]:border-primary"
                                            />
                                            <label className="flex-1 flex items-center gap-2 cursor-pointer">
                                                <span className="text-xs text-foreground">{method.display_name || method.name}</span>
                                                <span className="text-xs text-muted-foreground ml-auto">{method.description}</span>
                                            </label>
                                        </>
                                    ) : (
                                        <>
                                            <div className="w-1.5 h-1.5 rounded-full bg-primary/60" />
                                            <span className="text-xs text-foreground">{method.display_name || method.name}</span>
                                            <span className="text-xs text-muted-foreground ml-auto">{method.description}</span>
                                        </>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                )}
                {trigger.available_tools && trigger.available_tools.length > 0 && (
                    <div className="space-y-1">
                        <p className="text-xs font-medium text-foreground">Available Tools:</p>
                        <div className="space-y-1">
                            {trigger.available_tools.map((tool: any) => (
                                <div key={tool.name} className="flex items-center gap-2 p-1 rounded bg-muted/30">
                                    <div className="w-1.5 h-1.5 rounded-full bg-primary/60" />
                                    <span className="text-xs text-foreground">{tool.display_name || tool.name}</span>
                                    <span className="text-xs text-muted-foreground ml-auto">{tool.description}</span>
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </div>
        </CardAccordionItem>
    );
};