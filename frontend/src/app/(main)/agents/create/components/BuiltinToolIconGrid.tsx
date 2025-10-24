import React, { useState } from "react";
import {
  Calculator,
  ChevronDown,
  ChevronUp,
  Files,
  Globe,
  Settings,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { cn } from "@/lib/utils";

type BuiltinTool = {
  name: string;
  display_name: string;
  description: string;
  category?: string;
  available_methods?: Array<{
    name: string;
    display_name: string;
    description: string;
  }>;
};

type ToolConfig = {
  tool_name: string;
  disabled_methods?: { [methodName: string]: boolean };
};

type BuiltinToolIconGridProps = {
  builtinTools: BuiltinTool[];
  selectedTools: ToolConfig[];
  onAddTool: (toolName: string) => void;
  onRemoveTool: (toolName: string) => void;
  onUpdateToolConfig: (
    toolName: string,
    disabledMethods: { [methodName: string]: boolean }
  ) => void;
  loading?: boolean;
};

// Icon mapping for different tools
const getToolIcon = (toolName: string, category?: string) => {
  switch (toolName) {
    case "calculator":
      return Calculator;
    case "math_toolset":
      return Calculator;
    case "file_toolset":
      return Files;
    case "web_toolset":
      return Globe;
    default:
      // Default icon based on category
      switch (category) {
        case "math":
          return Calculator;
        case "utility":
          return Settings;
        case "information":
          return Globe;
        default:
          return Settings;
      }
  }
};

export const BuiltinToolIconGrid = ({
  builtinTools,
  selectedTools,
  onAddTool,
  onRemoveTool,
  onUpdateToolConfig,
  loading = false,
}: BuiltinToolIconGridProps) => {
  const [expandedTools, setExpandedTools] = useState<Set<string>>(new Set());

  const isToolSelected = (toolName: string) => {
    return selectedTools.some((config) => config.tool_name === toolName);
  };

  const getToolConfig = (toolName: string) => {
    return selectedTools.find((config) => config.tool_name === toolName);
  };

  const handleToolToggle = (toolName: string) => {
    if (isToolSelected(toolName)) {
      onRemoveTool(toolName);
      // Collapse when removing
      setExpandedTools((prev) => {
        const newSet = new Set(prev);
        newSet.delete(toolName);
        return newSet;
      });
    } else {
      onAddTool(toolName);
    }
  };

  const toggleExpanded = (toolName: string) => {
    setExpandedTools((prev) => {
      const newSet = new Set(prev);
      if (newSet.has(toolName)) {
        newSet.delete(toolName);
      } else {
        newSet.add(toolName);
      }
      return newSet;
    });
  };

  const handleMethodToggle = (
    toolName: string,
    methodName: string,
    enabled: boolean
  ) => {
    const toolConfig = getToolConfig(toolName);
    const currentDisabled = toolConfig?.disabled_methods || {};

    const newDisabledMethods = { ...currentDisabled };
    if (enabled) {
      // Remove from disabled list (method is now enabled)
      delete newDisabledMethods[methodName];
    } else {
      // Add to disabled list
      newDisabledMethods[methodName] = false;
    }

    onUpdateToolConfig(toolName, newDisabledMethods);
  };

  const isMethodEnabled = (toolName: string, methodName: string) => {
    const toolConfig = getToolConfig(toolName);
    const disabledMethods = toolConfig?.disabled_methods || {};
    return disabledMethods[methodName] !== false;
  };

  if (loading) {
    return (
      <div className="space-y-3">
        <h4 className="text-sm font-medium text-foreground">Built-in Tools</h4>
        <div className="flex items-center justify-center p-8 text-sm text-muted-foreground">
          Loading tools...
        </div>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div>
        <h4 className="text-sm font-medium text-foreground">Built-in Tools</h4>
        <p className="text-xs text-muted-foreground">
          Tap to enable tools for your agent
        </p>
      </div>

      <div className="space-y-3">
        {builtinTools.map((tool) => {
          const isSelected = isToolSelected(tool.name);
          const isExpanded = expandedTools.has(tool.name);
          const IconComponent = getToolIcon(tool.name, tool.category);
          const hasMethodSelection =
            tool.available_methods && tool.available_methods.length > 0;
          const toolConfig = getToolConfig(tool.name);
          const enabledMethodsCount = hasMethodSelection
            ? tool.available_methods!.filter((method) =>
                isMethodEnabled(tool.name, method.name)
              ).length
            : 0;

          return (
            <div key={tool.name} className="space-y-2">
              {/* Main tool card */}
              <Card
                className={cn(
                  "relative transition-all duration-200 ease-out",
                  "border-0 shadow-sm hover:shadow-md",
                  isSelected
                    ? "bg-primary/8 ring-1 ring-primary/20"
                    : "bg-background hover:bg-muted/30"
                )}
              >
                <div
                  className="flex cursor-pointer items-center p-3"
                  onClick={() => handleToolToggle(tool.name)}
                >
                  {/* Icon */}
                  <div
                    className={cn(
                      "flex h-8 w-8 items-center justify-center rounded-lg transition-colors",
                      isSelected ? "bg-primary/15" : "bg-muted/50"
                    )}
                  >
                    <IconComponent
                      className={cn(
                        "h-4 w-4 transition-colors",
                        isSelected ? "text-primary" : "text-muted-foreground"
                      )}
                    />
                  </div>

                  {/* Tool info */}
                  <div className="ml-3 min-w-0 flex-1">
                    <div className="flex items-center justify-between">
                      <p
                        className={cn(
                          "truncate text-sm font-medium",
                          isSelected ? "text-primary" : "text-foreground"
                        )}
                      >
                        {tool.display_name}
                      </p>

                      {/* Method count or expand button */}
                      <div className="ml-2 flex items-center space-x-2">
                        {isSelected && hasMethodSelection && (
                          <span className="rounded-full bg-muted/50 px-2 py-0.5 text-xs text-muted-foreground">
                            {enabledMethodsCount}/
                            {tool.available_methods!.length}
                          </span>
                        )}

                        {isSelected && hasMethodSelection && (
                          <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-6 w-6 p-0 hover:bg-primary/10"
                            onClick={(e) => {
                              e.stopPropagation();
                              toggleExpanded(tool.name);
                            }}
                          >
                            {isExpanded ? (
                              <ChevronUp className="h-3 w-3" />
                            ) : (
                              <ChevronDown className="h-3 w-3" />
                            )}
                          </Button>
                        )}
                      </div>
                    </div>

                    {!isExpanded && (
                      <p className="mt-0.5 truncate text-xs text-muted-foreground">
                        {tool.description}
                      </p>
                    )}
                  </div>

                  {/* Selection indicator */}
                  {isSelected && (
                    <div className="ml-2 h-2 w-2 rounded-full bg-primary" />
                  )}
                </div>

                {/* Method selection (expanded) */}
                {isSelected && isExpanded && hasMethodSelection && (
                  <div className="space-y-2 border-t border-border/50 p-3 pt-2">
                    <p className="mb-2 text-xs text-muted-foreground">
                      {tool.description}
                    </p>

                    <div className="space-y-1.5">
                      {tool.available_methods!.map((method) => {
                        const isEnabled = isMethodEnabled(
                          tool.name,
                          method.name
                        );

                        return (
                          <div
                            key={method.name}
                            className="flex items-start space-x-2"
                          >
                            <Checkbox
                              id={`${tool.name}-${method.name}`}
                              checked={isEnabled}
                              onCheckedChange={(checked) =>
                                handleMethodToggle(
                                  tool.name,
                                  method.name,
                                  checked as boolean
                                )
                              }
                              className="mt-0.5"
                            />
                            <div className="min-w-0 flex-1">
                              <label
                                htmlFor={`${tool.name}-${method.name}`}
                                className="cursor-pointer text-xs font-medium text-foreground"
                              >
                                {method.display_name}
                              </label>
                              <p className="truncate text-xs text-muted-foreground">
                                {method.description}
                              </p>
                            </div>
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}
              </Card>
            </div>
          );
        })}
      </div>

      {/* Selected tools summary */}
      {selectedTools.length > 0 && (
        <div className="border-t border-border/30 pt-2">
          <p className="text-xs text-muted-foreground">
            <span className="font-medium">{selectedTools.length}</span> tool
            {selectedTools.length !== 1 ? "s" : ""} enabled
          </p>
        </div>
      )}
    </div>
  );
};
