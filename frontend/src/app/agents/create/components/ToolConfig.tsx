import React from "react";
import { Cpu, Trash2, Zap} from "lucide-react";
import { FieldErrors, UseFieldArrayReturn, UseFieldArrayAppend } from 'react-hook-form';
import { getNestedErrorMessage } from "../utils/formUtils";
import type { AgentFormValues } from "../types";
import type { components } from '@/api/schema';
import AccordionControl from "./AccordionControl";
import { Button } from "@/components/ui/button";
import { Plus } from "lucide-react";
import { useState, useEffect } from "react";
import { TriggerControl } from "./TriggerControl";
import { Accordion } from "@/components/ui/accordion";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription, SheetTrigger } from "@/components/ui/sheet";
import SelectMcp from "./SelectMcp";
import { useTranslations } from "next-intl";

type MCPServer = components["schemas"]["MCPServerResponse"];


type ToolConfigProps = {
  control: any;
  errors: FieldErrors<AgentFormValues>;
  toolFields: UseFieldArrayReturn<AgentFormValues, "tools_config.mcp_server_configs", "id">["fields"];
  removeTool: (index: number) => void;
  appendTool: UseFieldArrayAppend<AgentFormValues, "tools_config.mcp_server_configs">;
  mcpServers: MCPServer[];
};

const ToolConfig = ({ control, errors, toolFields, removeTool, appendTool, mcpServers }: ToolConfigProps) => {
  const [accordionValue, setAccordionValue] = useState<string>("tools");
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const [scrollToolId, setScrollToolId] = useState<string | null>(null);
  const t = useTranslations('AgentsPage');
  const title = (
    <div className="flex items-center gap-2">
      <Cpu className="label-icon" style={{ strokeWidth: 1.5 }} /> Tools (MCP Servers)
    </div>
  );
  const note = (
    <p>
      Add MCP Servers to your agent to enable tool use.
    </p>
  );

  const mcpServerTEST = [
    {id: 'mcp_server_id', name: 'MCP Server1', icon: <Cpu className="h-4 w-4" />},
    {id: 'mcp_server_id1', name: 'MCP Server2', icon: <Zap className="h-4 w-4" />},
    {id: 'mcp_server_id2', name: 'MCP Server3', icon: <Trash2 className="h-4 w-4" />},
  ];

  // Helper converts raw MCP server objects to form-compatible configs
  const handleAddTools = (servers: MCPServer[]) => {
    if (!servers?.length) return;
    const configs = servers.map((server) => ({
      mcp_server_id: server.id,
      api_key: "",
      config: null,
      enabled: true,
    }));
    appendTool(configs);
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
        <Sheet modal={false} open={isSheetOpen} onOpenChange={setIsSheetOpen}>
        <SheetTrigger asChild>
          <Button size="xs">
            <Plus className="h-4 w-4" />
            Tool
          </Button>
        </SheetTrigger>
        <SheetContent className="w-full flex flex-col sm:w-[540px] overflow-y-hidden pb-0"  disableOutsideClose>
          <SheetHeader className="mb-[12px] md:mb-[24px]">
            <SheetTitle>{t('create.toolsMcp')}</SheetTitle>
            <SheetDescription className="text-xs">
              {t('create.toolsMcpDescription')}
            </SheetDescription>
          </SheetHeader>
          <SelectMcp 
            mcpServers={mcpServers} 
            onAddTools={handleAddTools} 
            acceptedTools={toolFields.map(item => item.mcp_server_id)} 
            openToolId={scrollToolId}
          />
        </SheetContent>
      </Sheet>
      }
    >
          <div className="space-y-6">
      {toolFields.length > 0 ? (
        <Accordion type="multiple" id="tools-items">
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






// (
      //   <div key={item.id} className="mt-2 p-4 border rounded-md space-y-3 relative bg-slate-50/80 shadow-sm">
      //     <Button
      //       type="button"
      //       variant="ghost"
      //       size="icon"
      //       onClick={() => removeTool(index)}
      //       className="absolute top-1 right-1 text-muted-foreground hover:text-red-500 h-7 w-7"
      //       aria-label="Remove Tool"
      //     >
      //       <Trash2 className="h-4 w-4" />
      //     </Button>
      //     <div className="pt-2">
      //       <Label htmlFor={`tools_config.mcp_server_configs.${index}.mcp_server_id`} className="text-sm">MCP Server</Label>
      //       <Controller
      //           name={`tools_config.mcp_server_configs.${index}.mcp_server_id`}
      //           control={control}
      //           rules={{ required: "MCP Server selection is required" }}
      //           render={({ field }) => (
      //               <Select onValueChange={field.onChange} value={field.value ?? ''}>
      //                 <SelectTrigger className="mt-1">
      //                   <SelectValue placeholder="Select MCP Server" />
      //                 </SelectTrigger>
      //                 <SelectContent>
      //                   {mcpServers.map((server) => (
      //                     <SelectItem key={server.id} value={server.id}>{server.name}</SelectItem>
      //                   ))}
      //                 </SelectContent>
      //               </Select>
      //             )}
      //        />
      //       {getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.mcp_server_id`) && 
      //        <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.mcp_server_id`)}</p>}
      //     </div>
      //     <div>
      //       <Label htmlFor={`tools_config.mcp_server_configs.${index}.api_key`} className="text-sm">API Key</Label>
      //       <Controller
      //         name={`tools_config.mcp_server_configs.${index}.api_key`}
      //         control={control}
      //         render={({ field }) => (
      //           <Input
      //             id={`tools_config.mcp_server_configs.${index}.api_key`}
      //             type="password"
      //             {...field}
      //             placeholder="Enter API Key"
      //             className="mt-1"
      //             aria-invalid={!!getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.api_key`)}
      //           />
      //         )}
      //       />
      //       {getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.api_key`) && 
      //        <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.api_key`)}</p>}
      //     </div>
      //      <div>
      //         <Label htmlFor={`tools_config.mcp_server_configs.${index}.config`} className="text-sm">Specific Config (JSON, optional)</Label>
      //         <Controller
      //           name={`tools_config.mcp_server_configs.${index}.config`}
      //           control={control}
      //           render={({ field }) => (
      //             <Textarea
      //               id={`tools_config.mcp_server_configs.${index}.config`}
      //               value={field.value && typeof field.value === 'object' ? JSON.stringify(field.value, null, 2) : ''}
      //               onChange={(e) => {
      //                 try {
      //                   const parsed = JSON.parse(e.target.value || '{}');
      //                   field.onChange(parsed);
      //                 } catch {
      //                   field.onChange(e.target.value);
      //                 }
      //               }}
      //               placeholder='{ \"parameter\": \"value\" }'
      //               className="mt-1 font-mono text-sm h-24"
      //               aria-invalid={!!getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.config`)}
      //             />
      //           )}
      //         />
      //         {getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.config`) && 
      //          <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.config`)}</p>}
      //       </div>
      //   </div>
      // )