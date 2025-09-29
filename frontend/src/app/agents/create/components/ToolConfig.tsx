import React from "react";
import { Cpu, Calculator } from "lucide-react";
import { FieldErrors, UseFieldArrayReturn, UseFieldArrayAppend } from 'react-hook-form';
import { getNestedErrorMessage } from "../utils/formUtils";
import type { AgentFormValues, BuiltinToolConfig } from "../types";
import type { components } from '@/api/schema';
import { useState, useEffect } from "react";
import { TriggerControl } from "./TriggerControl";
import { Accordion } from "@/components/ui/accordion";
import { SelectableList } from "./SelectableList";
import { useTranslations } from "next-intl";
import ConfigSheet from "./ConfigSheet";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { BuiltinToolIconGrid } from "./BuiltinToolIconGrid";

type MCPServer = components["schemas"]["MCPServerResponse"];


type ToolConfigProps = {
  control: any;
  errors: FieldErrors<AgentFormValues>;
  toolFields: UseFieldArrayReturn<AgentFormValues, "tools_config.mcp_server_configs", "id">["fields"];
  removeTool: (index: number) => void;
  appendTool: UseFieldArrayAppend<AgentFormValues, "tools_config.mcp_server_configs">;
  mcpServers: MCPServer[];
  mcpInstanceList: any[];
  builtinTools: any[];
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
  builtinTools,
  builtinToolFields,
  removeBuiltinTool,
  appendBuiltinTool
}: ToolConfigProps) => {
  const [accordionValue, setAccordionValue] = useState<string>("tools");
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const [scrollToolId, setScrollToolId] = useState<string | null>(null);
  const [loadingBuiltinTools, setLoadingBuiltinTools] = useState(false);
  const t = useTranslations('AgentsPage');


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