import { Edit, Trash2 } from "lucide-react";
import { Control, useWatch, type Path } from "react-hook-form";
import { CardAccordionItem } from "@/components/CardAccordionItem/CardAccordionItem";
import { Button } from "@/components/ui/button";
import type { AgentFormValues, MCPToolConfig } from "../types";
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
  iconSrc?: string;
  available_methods?: Method[];
  available_tools?: Array<{
    name: string;
    display_name?: string;
    description?: string;
  }>;
}

type ToolState = "disabled" | "enabled" | "approval_required";

interface TriggerControlProps {
  trigger: Trigger | undefined;
  index: number;
  name: string;
  enabledName: string;
  control: Control<AgentFormValues>;
  removeEvent?: (index: number) => void;
  editEvent?: (index: number) => void;
  // Builtin tool methods
  selectedMethods?: Record<string, boolean>;
  onMethodToggle?: (methodName: string, checked: boolean) => void;
  // MCP tool-level control
  allowedToolsFieldName?: string;
  onToolStateChange?: (toolName: string, state: ToolState) => void;
}

export const TriggerControl = ({
  trigger,
  index,
  control,
  removeEvent,
  editEvent,
  name: _name,
  enabledName: _enabledName,
  selectedMethods = {},
  onMethodToggle,
  allowedToolsFieldName,
  onToolStateChange,
}: TriggerControlProps) => {
  // Reactively watch allowed_tools so checkboxes update on change
  const watchedAllowedTools = useWatch({
    control,
    name: allowedToolsFieldName as Path<AgentFormValues>,
    defaultValue: [],
  });
  const allowedTools: MCPToolConfig[] = Array.isArray(watchedAllowedTools)
    ? watchedAllowedTools
    : [];

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

  const availableTools = trigger.available_tools || [];
  const hasTools = availableTools.length > 0;
  const hasToolControl = !!onToolStateChange;

  // Compute selected counts for badge
  const selectedMethodCount =
    hasMethods && hasMethodToggle
      ? availableMethods.filter((m) => selectedMethods[m.name] === true).length
      : 0;

  const getToolEnabled = (toolName: string): boolean => {
    if (!allowedTools || allowedTools.length === 0) return true;
    return allowedTools.some((t) => t.tool_name === toolName);
  };

  const getToolApproval = (toolName: string): boolean => {
    if (!allowedTools) return false;
    const config = allowedTools.find((t) => t.tool_name === toolName);
    return config?.requires_user_confirmation ?? false;
  };

  const enabledToolCount =
    hasTools && hasToolControl
      ? availableTools.filter((t) => getToolEnabled(t.name)).length
      : availableTools.length;

  // Build selectedMethods-style map for tools
  const toolSelectionMap: Record<string, boolean> = {};
  const toolApprovalMap: Record<string, boolean> = {};
  for (const tool of availableTools) {
    toolSelectionMap[tool.name] = getToolEnabled(tool.name);
    toolApprovalMap[tool.name] = getToolApproval(tool.name);
  }

  const handleSelectAllMethods = (checked: boolean) => {
    if (!onMethodToggle || !hasMethods) return;
    availableMethods.forEach((method) => onMethodToggle(method.name, checked));
  };

  const handleToolToggle = (toolName: string, checked: boolean) => {
    if (!onToolStateChange) return;
    onToolStateChange(toolName, checked ? "enabled" : "disabled");
  };

  const handleToolApprovalToggle = (
    toolName: string,
    requiresApproval: boolean
  ) => {
    if (!onToolStateChange) return;
    onToolStateChange(
      toolName,
      requiresApproval ? "approval_required" : "enabled"
    );
  };

  const handleSelectAllTools = (checked: boolean) => {
    if (!onToolStateChange) return;
    availableTools.forEach((tool) =>
      onToolStateChange(tool.name, checked ? "enabled" : "disabled")
    );
  };

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
        <Edit />
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
        <Trash2 />
      </Button>
    );
  };

  const badgeCount =
    hasMethods && hasMethodToggle
      ? `${selectedMethodCount}/${availableMethods.length}`
      : hasTools && hasToolControl
        ? `${enabledToolCount}/${availableTools.length}`
        : null;

  const controls = (
    <div className="flex flex-row items-center gap-3">
      {badgeCount && (
        <span className="min-w-[50px] rounded-full bg-primary/15 px-2 py-0.5 text-center text-xs text-muted-foreground">
          {badgeCount}
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

  return (
    <CardAccordionItem
      value={`trigger-${index}`}
      controls={controls}
      title={renderTitle()}
      iconSrc={trigger.icon ? undefined : trigger.iconSrc || "/Icon.svg"}
    >
      <div className="space-y-2">
        <p className="text-xs text-muted-foreground">
          {trigger.description || trigger.label || trigger.name}
        </p>

        {/* Builtin tool methods */}
        {hasMethods && (
          <MethodsList
            methods={availableMethods}
            selectedMethods={
              hasMethodToggle
                ? selectedMethods
                : Object.fromEntries(
                    availableMethods.map((m) => [m.name, true])
                  )
            }
            onMethodToggle={onMethodToggle || (() => {})}
            toolName={trigger.name || trigger.id || `trigger-${index}`}
            showSelectAll={hasMethodToggle}
            onSelectAll={hasMethodToggle ? handleSelectAllMethods : undefined}
            label="Available Methods:"
          />
        )}

        {/* MCP tools — same component, with approval toggle */}
        {hasTools && (
          <MethodsList
            methods={availableTools}
            selectedMethods={toolSelectionMap}
            onMethodToggle={hasToolControl ? handleToolToggle : () => {}}
            toolName={trigger.name || trigger.id || `trigger-${index}`}
            showSelectAll={hasToolControl}
            onSelectAll={hasToolControl ? handleSelectAllTools : undefined}
            approvalStates={hasToolControl ? toolApprovalMap : undefined}
            onApprovalToggle={
              hasToolControl ? handleToolApprovalToggle : undefined
            }
            label={`Available Tools (${enabledToolCount}/${availableTools.length}):`}
          />
        )}
      </div>
    </CardAccordionItem>
  );
};
