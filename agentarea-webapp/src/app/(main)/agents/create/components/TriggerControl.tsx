import { Edit, Trash2 } from "lucide-react";
import { Control, Controller } from "react-hook-form";
import { CardAccordionItem } from "@/components/CardAccordionItem/CardAccordionItem";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import type { AgentFormValues } from "../types";
import { MethodsList } from "./MethodsList";

interface Method {
  name: string;
  display_name?: string;
  description?: string;
}

interface Trigger {
  id?: string;
  name: string;
  label?: string;
  description?: string;
  icon?: React.ComponentType<{ className?: string }>;
  available_methods?: Method[];
  available_tools?: Array<{
    name: string;
    display_name?: string;
    description?: string;
  }>;
}

interface TriggerControlProps {
  trigger: Trigger | undefined;
  index: number;
  name: string;
  enabledName: string;
  control: Control<AgentFormValues>;
  removeEvent?: (index: number) => void;
  editEvent?: (index: number) => void;
  selectedMethods?: Record<string, boolean>;
  onMethodToggle?: (methodName: string, checked: boolean) => void;
}

export const TriggerControl = ({
  trigger,
  index,
  control,
  removeEvent,
  editEvent,
  name,
  enabledName,
  selectedMethods = {},
  onMethodToggle,
}: TriggerControlProps) => {
  if (!trigger) {
    return (
      <div className="mt-1 flex items-center gap-2 text-red-500">
        Something went wrong with the trigger
      </div>
    );
  }

  const availableMethods = trigger.available_methods || [];
  const hasMethods = availableMethods.length > 0;
  const hasMethodToggle = !!onMethodToggle;

  // Calculate selected methods count for indicator
  const selectedCount = hasMethods && hasMethodToggle
    ? availableMethods.filter(
        (method) => selectedMethods[method.name] === true
      ).length
    : 0;
  const totalCount = availableMethods.length;

  const handleSelectAllMethods = (checked: boolean) => {
    if (!onMethodToggle || !hasMethods) return;

    availableMethods.forEach((method) => {
      onMethodToggle(method.name, checked);
    });
  };


  const renderEnabledSwitch = () => (
    <Controller
      name={enabledName as any}
      control={control}
      defaultValue={true}
      render={({ field }) => (
        <div className="flex items-center gap-1">
          <span
            className="note hidden cursor-pointer select-none sm:block"
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
  );

  const renderEditButton = () => {
    if (!editEvent) return null;

    return (
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={() => editEvent(index)}
        className="h-4 w-4 flex-shrink-0 text-muted-foreground/60 hover:bg-transparent hover:text-primary"
        aria-label="Edit Event"
      >
        <Edit className="h-4 w-4" />
      </Button>
    );
  };

  const renderRemoveButton = () => {
    if (!removeEvent) return null;

    return (
      <Button
        type="button"
        variant="ghost"
        size="icon"
        onClick={() => removeEvent(index)}
        className="h-4 w-4 flex-shrink-0 text-muted-foreground/60 hover:bg-transparent hover:text-red-500"
        aria-label="Remove Event"
      >
        <Trash2 className="h-4 w-4" />
      </Button>
    );
  };

  const controls = (
    <div className="flex flex-row items-center gap-3">
      {/* {renderEnabledSwitch()} */}
      {hasMethods && hasMethodToggle && totalCount > 0 && (
        <span className="min-w-[50px] rounded-full bg-primary/15 px-2 py-0.5 text-center text-xs text-muted-foreground">
          {selectedCount}/{totalCount}
        </span>
      )}
      {renderEditButton()}
      {renderRemoveButton()}
    </div>
  );

  const renderTitle = () => {
    if (!trigger.icon) {
      return trigger.label || trigger.name;
    }

    return (
      <div className="flex flex-row items-center gap-1 px-[7px] py-[7px]">
        <trigger.icon className="h-4 w-4 text-muted-foreground" />
        <h3 className="text-sm font-medium transition-colors duration-300 group-hover:text-accent group-data-[state=open]:text-accent dark:group-hover:text-accent dark:group-data-[state=open]:text-accent">
          {trigger.label || trigger.name}
        </h3>
      </div>
    );
  };

  const renderMethodsSection = () => {
    if (!hasMethods) return null;

    if (hasMethodToggle) {
      return (
        <MethodsList
          methods={availableMethods}
          selectedMethods={selectedMethods}
          onMethodToggle={onMethodToggle!}
          toolName={trigger.name || trigger.id || `trigger-${index}`}
          showSelectAll={true}
          onSelectAll={handleSelectAllMethods}
        />
      );
    }

    return (
      <div className="space-y-1">
        <p className="text-xs font-medium text-foreground">
          Available Methods:
        </p>
        <div className="space-y-1">
          {availableMethods.map((method) => (
            <div
              key={method.name}
              className="flex items-center gap-2 rounded bg-muted/30 p-1"
            >
              <div className="h-1.5 w-1.5 rounded-full bg-primary/60" />
              <span className="text-xs text-foreground">
                {method.display_name || method.name}
              </span>
              <span className="ml-auto text-xs text-muted-foreground">
                {method.description}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  const renderToolsSection = () => {
    if (!trigger.available_tools || trigger.available_tools.length === 0)
      return null;

    return (
      <div className="space-y-1">
        <p className="text-xs font-medium text-foreground">Available Tools:</p>
        <div className="space-y-1">
          {trigger.available_tools.map((tool) => (
            <div
              key={tool.name}
              className="flex items-center gap-2 rounded bg-muted/30 p-1"
            >
              <div className="h-1.5 w-1.5 rounded-full bg-primary/60" />
              <span className="text-xs text-foreground">
                {tool.display_name || tool.name}
              </span>
              <span className="ml-auto text-xs text-muted-foreground">
                {tool.description}
              </span>
            </div>
          ))}
        </div>
      </div>
    );
  };

  return (
    <CardAccordionItem
      value={`trigger-${index}`}
      controls={controls}
      title={renderTitle()}
      iconSrc={trigger.icon ? undefined : "/Icon.svg"}
    >
      <div className="space-y-2">
        <p className="text-xs text-muted-foreground">
          {trigger.description || trigger.label || trigger.name}
        </p>
        {renderMethodsSection()}
        {renderToolsSection()}
      </div>
    </CardAccordionItem>
  );
};
