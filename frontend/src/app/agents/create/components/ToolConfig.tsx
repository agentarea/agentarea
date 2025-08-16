import React from "react";
import { Cpu, Calculator, Wrench, Plus, Trash2 } from "lucide-react";
import { FieldErrors, UseFieldArrayReturn, UseFieldArrayAppend } from 'react-hook-form';
import { getNestedErrorMessage } from "../utils/formUtils";
import type { AgentFormValues, BuiltinToolConfig } from "../types";
import type { components } from '@/api/schema';
import AccordionControl from "./AccordionControl";
import { useState, useEffect } from "react";
import { TriggerControl } from "./TriggerControl";
import { Accordion } from "@/components/ui/accordion";
import { SelectableList } from "./SelectableList";
import { useTranslations } from "next-intl";
import FormLabel from "@/components/FormLabel/FormLabel";
import ConfigSheet from "./ConfigSheet";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { BuiltinToolIconGrid } from "./BuiltinToolIconGrid";
import { client } from '@/lib/api';

type MCPServer = components["schemas"]["MCPServerResponse"];

// Builtin tools will be fetched from API - for now using static data
const BUILTIN_TOOLS = [
  {
    name: "calculator",
    display_name: "Calculator", 
    description: "Perform basic mathematical calculations like addition, subtraction, multiplication, division",
    category: "utility"
  },
  {
    name: "math_toolset",
    display_name: "Math Toolset",
    description: "Mathematical operations including addition, subtraction, multiplication, division, and more",
    category: "math",
    available_methods: [
      { name: "add", display_name: "Addition", description: "Add two numbers together" },
      { name: "subtract", display_name: "Subtraction", description: "Subtract one number from another" },
      { name: "multiply", display_name: "Multiplication", description: "Multiply two numbers" },
      { name: "divide", display_name: "Division", description: "Divide one number by another" },
      { name: "power", display_name: "Power/Exponentiation", description: "Raise a number to a power" },
      { name: "sqrt", display_name: "Square Root", description: "Calculate the square root of a number" },
      { name: "sin", display_name: "Sine", description: "Calculate the sine of an angle" },
      { name: "cos", display_name: "Cosine", description: "Calculate the cosine of an angle" },
      { name: "tan", display_name: "Tangent", description: "Calculate the tangent of an angle" },
      { name: "log", display_name: "Logarithm", description: "Calculate the logarithm of a number" },
      { name: "abs", display_name: "Absolute Value", description: "Calculate the absolute value of a number" },
      { name: "evaluate", display_name: "Expression Evaluator", description: "Safely evaluate mathematical expressions" }
    ]
  }
];

type ToolConfigProps = {
  control: any;
  errors: FieldErrors<AgentFormValues>;
  toolFields: UseFieldArrayReturn<AgentFormValues, "tools_config.mcp_server_configs", "id">["fields"];
  removeTool: (index: number) => void;
  appendTool: UseFieldArrayAppend<AgentFormValues, "tools_config.mcp_server_configs">;
  mcpServers: MCPServer[];
  mcpInstanceList: any[];
  builtinToolFields?: UseFieldArrayReturn<AgentFormValues, "tools_config.builtin_tools", "id">["fields"];
  removeBuiltinTool?: (index: number) => void;
  appendBuiltinTool?: UseFieldArrayAppend<AgentFormValues, "tools_config.builtin_tools">;
};

const ToolConfig = ({ 
  control, 
  errors, 
  toolFields, 
  removeTool, 
  appendTool, 
  mcpServers, 
  mcpInstanceList,
  builtinToolFields,
  removeBuiltinTool,
  appendBuiltinTool
}: ToolConfigProps) => {
  const [accordionValue, setAccordionValue] = useState<string>("tools");
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const [scrollToolId, setScrollToolId] = useState<string | null>(null);
  const [builtinTools, setBuiltinTools] = useState<any[]>([]);
  const [loadingBuiltinTools, setLoadingBuiltinTools] = useState(false);
  const t = useTranslations('AgentsPage');

  // Fetch builtin tools from API
  useEffect(() => {
    const fetchBuiltinTools = async () => {
      setLoadingBuiltinTools(true);
      try {
        const response = await client.GET('/v1/agents/tools/builtin');
        if (response.data) {
          // Convert the object to array format
          const toolsArray = Object.values(response.data).map((tool: any) => ({
            name: tool.name,
            display_name: tool.display_name,
            description: tool.description,
            category: tool.category,
            available_methods: tool.available_methods || []
          }));
          setBuiltinTools(toolsArray);
        }
      } catch (error) {
        console.error('Failed to fetch builtin tools:', error);
        // Fallback to static data
        setBuiltinTools(BUILTIN_TOOLS);
      } finally {
        setLoadingBuiltinTools(false);
      }
    };

    fetchBuiltinTools();
  }, []);

  // Builtin tools helpers for unified selector
  const handleAddBuiltinTool = (toolName: string) => {
    if (!appendBuiltinTool) return;
    
    const exists = builtinToolFields?.some(field => field.tool_name === toolName) || false;
    if (!exists) {
      appendBuiltinTool({ tool_name: toolName });
    }
  };

  const handleRemoveBuiltinTool = (toolName: string) => {
    if (!removeBuiltinTool) return;
    
    const index = builtinToolFields?.findIndex(field => field.tool_name === toolName) ?? -1;
    if (index !== -1) {
      removeBuiltinTool(index);
    }
  };

  const handleUpdateBuiltinToolConfig = (toolName: string, disabledMethods: { [methodName: string]: boolean }) => {
    if (!builtinToolFields || !removeBuiltinTool || !appendBuiltinTool) return;
    
    const index = builtinToolFields.findIndex(field => field.tool_name === toolName);
    if (index !== -1) {
      // Update existing tool config
      removeBuiltinTool(index);
      appendBuiltinTool({ 
        tool_name: toolName,
        disabled_methods: Object.keys(disabledMethods).length > 0 ? disabledMethods : undefined
      });
    }
  };

  const getSelectedBuiltinTools = () => {
    return builtinToolFields?.map(field => ({
      tool_name: field.tool_name,
      disabled_methods: field.disabled_methods || {}
    })) || [];
  };

  // MCP server helpers  
  const handleAddTools = (servers: MCPServer[]) => {
    if (!servers?.length) return;
    const configs = servers.map((server) => ({
      mcp_server_id: server.id,
      allowed_tools: [],
    }));
    appendTool(configs);
  };

  const handleRemoveTool = (serverId: string) => {
    const idx = toolFields.findIndex((item) => item.mcp_server_id === serverId);
    if (idx !== -1) {
      removeTool(idx);
    }
  };

  const editTool = (index: number) => {
    const tool = toolFields[index];
    if (!tool) return;
    setScrollToolId(tool.mcp_server_id);
    setIsSheetOpen(true);
  };

  useEffect(() => {
    if (isSheetOpen && scrollToolId) {
      const timer = setTimeout(() => {
        const el = document.getElementById(`mcp-${scrollToolId}`);
        el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [isSheetOpen, scrollToolId]);

  return (
    <div className="space-y-6">
      {/* Builtin Tools Section */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Calculator className="h-4 w-4" />
            Tools Configuration
          </CardTitle>
        </CardHeader>
        <CardContent>
          <BuiltinToolIconGrid
            builtinTools={builtinTools}
            selectedTools={getSelectedBuiltinTools()}
            onAddTool={handleAddBuiltinTool}
            onRemoveTool={handleRemoveBuiltinTool}
            onUpdateToolConfig={handleUpdateBuiltinToolConfig}
            loading={loadingBuiltinTools}
          />
        </CardContent>
      </Card>

      {/* MCP Servers Section */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <Cpu className="h-4 w-4" />
            MCP Servers
            <ConfigSheet
              title={t('create.toolsMcp')}
              description={t('create.toolsMcpDescription')}
              triggerText="Add MCP Server"
              className="ml-auto"
              open={isSheetOpen}
              onOpenChange={setIsSheetOpen}
            >
              <div className="flex flex-col overflow-y-auto space-y-4">
                <div className="font-semibold">Active MCP Servers</div>
                <SelectableList
                  items={mcpInstanceList}
                  prefix="active-mcp"
                  extractTitle={(instance) => instance.name || instance.id}
                  onAdd={(instance) => handleAddTools([instance])}
                  onRemove={(instance) => handleRemoveTool(instance.id)}
                  selectedIds={toolFields.map((item) => item.mcp_server_id)}
                  openItemId={scrollToolId}
                  renderContent={() => (
                    <div className="p-4 text-sm text-muted-foreground">Active</div>
                  )}
                />
                <div className="font-semibold">Available MCP Servers</div>
                <SelectableList
                  items={mcpServers}
                  prefix="mcp"
                  extractTitle={(server) => server.name}
                  onAdd={(server) => handleAddTools([server])}
                  onRemove={(server) => handleRemoveTool(server.id)}
                  selectedIds={toolFields.map((item) => item.mcp_server_id)}
                  openItemId={scrollToolId}
                  renderContent={() => (
                    <div className="p-4 text-sm text-muted-foreground">Available</div>
                  )}
                />
              </div>
            </ConfigSheet>
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="space-y-4">
            {toolFields.length > 0 ? (
              <Accordion type="multiple" id="mcp-tools-items" className="space-y-2">
                {toolFields.map((item, index) => (
                  <TriggerControl 
                    name={`tools_config.mcp_server_configs.${index}.mcp_server_id`}
                    enabledName={`tools_config.mcp_server_configs.${index}.enabled`}
                    key={`tool-${index}`}
                    trigger={mcpServers.find(option => option.id === item.mcp_server_id) || undefined}
                    index={index}
                    control={control}
                    removeEvent={() => removeTool(index)}
                    editEvent={() => editTool(index)}
                  />
                ))}
              </Accordion>
            ) : (
              <div className="cursor-default mt-2 items-center gap-2 p-3 border rounded-md text-muted-foreground/50 text-xs text-center">
                Add MCP Servers to your agent to enable tool use.
              </div>
            )}
          </div>
        </CardContent>
      </Card>

      {/* Error Messages */}
      {getNestedErrorMessage(errors, 'tools_config.mcp_server_configs') && 
        <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'tools_config.mcp_server_configs')}</p>}
      {getNestedErrorMessage(errors, 'tools_config.builtin_tools') && 
        <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'tools_config.builtin_tools')}</p>}
      {getNestedErrorMessage(errors, 'tools_config') && 
        <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'tools_config')}</p>}
    </div>
  );
};

export default ToolConfig; 