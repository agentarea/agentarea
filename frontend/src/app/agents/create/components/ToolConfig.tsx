import React from "react";
import { Cpu, Trash2, Zap} from "lucide-react";
import { FieldErrors, UseFieldArrayReturn, UseFieldArrayAppend } from 'react-hook-form';
import { getNestedErrorMessage } from "../utils/formUtils";
import type { AgentFormValues } from "../types";
import type { components } from '@/api/schema';
import AccordionControl from "./AccordionControl";
import { useState, useEffect } from "react";
import { TriggerControl } from "./TriggerControl";
import { Accordion } from "@/components/ui/accordion";
import { SelectableList } from "./SelectableList";
import { useTranslations } from "next-intl";
import FormLabel from "@/components/FormLabel/FormLabel";
import ConfigSheet from "./ConfigSheet";

type MCPServer = components["schemas"]["MCPServerResponse"];


type ToolConfigProps = {
  control: any;
  errors: FieldErrors<AgentFormValues>;
  toolFields: UseFieldArrayReturn<AgentFormValues, "tools_config.mcp_server_configs", "id">["fields"];
  removeTool: (index: number) => void;
  appendTool: UseFieldArrayAppend<AgentFormValues, "tools_config.mcp_server_configs">;
  mcpServers: MCPServer[];
  mcpInstanceList: any[];
};

const ToolConfig = ({ control, errors, toolFields, removeTool, appendTool, mcpServers, mcpInstanceList }: ToolConfigProps) => {
  const [accordionValue, setAccordionValue] = useState<string>("tools");
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const [scrollToolId, setScrollToolId] = useState<string | null>(null);
  const t = useTranslations('AgentsPage');
  const title = (
    <div className="flex items-center gap-2">
      <FormLabel icon={Cpu} className="cursor-pointer">Tools (MCP Servers)</FormLabel>
    </div>
  );
  const note = (
    <p>
      Add MCP Servers to your agent to enable tool use.
    </p>
  );

  // Helper converts raw MCP server objects to form-compatible configs
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
  <>
    <AccordionControl
      id="tools"
      accordionValue={accordionValue}
      setAccordionValue={setAccordionValue}
      title={title}
      note={note}
      mainControl={
        <ConfigSheet
          title={t('create.toolsMcp')}
          description={t('create.toolsMcpDescription')}
          triggerText="Tool"
          className=""
        >
          <div className="flex flex-col overflow-y-auto space-y-1">
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
                <div className="p-4 text-sm text-muted-foreground">TEST</div>
              )}
            />
          </div>
        </ConfigSheet>
      }
    >
          <div className="space-y-6">
      {toolFields.length > 0 ? (
        <Accordion type="multiple" id="tools-items" className="space-y-2">
          {
            toolFields.map((item, index) => (
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
            ))
          }
        </Accordion>
      ) : (
        <div className="cursor-default mt-2 items-center gap-2 p-3 border rounded-md text-muted-foreground/50 text-xs text-center">
          {note}
        </div>
      )}
    </div>
    </AccordionControl>

     {getNestedErrorMessage(errors, 'tools_config.mcp_server_configs') && 
      <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'tools_config.mcp_server_configs')}</p>}
     {getNestedErrorMessage(errors, 'tools_config') && 
      <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'tools_config')}</p>}
  </>
);
}

export default ToolConfig; 