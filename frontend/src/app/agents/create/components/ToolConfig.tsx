import React from "react";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Cpu, Plus, Trash2 } from "lucide-react";
import { Controller, FieldErrors, UseFieldArrayReturn } from 'react-hook-form';
import { getNestedErrorMessage } from "../utils/formUtils";
import type { AgentFormValues } from "../types";
import type { components } from '@/api/schema';

type MCPServer = components["schemas"]["MCPServerResponse"];

type ToolConfigProps = {
  control: any;
  errors: FieldErrors<AgentFormValues>;
  toolFields: UseFieldArrayReturn<AgentFormValues, "tools_config.mcp_server_configs", "id">["fields"];
  removeTool: (index: number) => void;
  appendTool: (data: { mcp_server_id: string; api_key: string; config?: Record<string, unknown> | null }) => void;
  mcpServers: MCPServer[];
};

const ToolConfig = ({ control, errors, toolFields, removeTool, appendTool, mcpServers }: ToolConfigProps) => (
  <Card className="p-8 shadow-xl border-0 bg-white/90 hover:shadow-2xl transition-shadow">
    <h2 className="text-2xl font-bold mb-6 flex items-center gap-2">
      <Cpu className="h-5 w-5 text-blue-500" /> Tools (MCP Servers)
    </h2>
    <div className="space-y-6">
      {toolFields.map((item, index) => (
        <div key={item.id} className="p-4 border rounded-md space-y-3 relative bg-slate-50/80 shadow-sm">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => removeTool(index)}
            className="absolute top-1 right-1 text-muted-foreground hover:text-red-500 h-7 w-7"
            aria-label="Remove Tool"
          >
            <Trash2 className="h-4 w-4" />
          </Button>
          <div className="pt-2">
            <Label htmlFor={`tools_config.mcp_server_configs.${index}.mcp_server_id`} className="text-sm">MCP Server</Label>
            <Controller
                name={`tools_config.mcp_server_configs.${index}.mcp_server_id`}
                control={control}
                rules={{ required: "MCP Server selection is required" }}
                render={({ field }) => (
                    <Select onValueChange={field.onChange} value={field.value ?? ''}>
                      <SelectTrigger className="mt-1">
                        <SelectValue placeholder="Select MCP Server" />
                      </SelectTrigger>
                      <SelectContent>
                        {mcpServers.map((server) => (
                          <SelectItem key={server.id} value={server.id}>{server.name}</SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  )}
             />
            {getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.mcp_server_id`) && 
             <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.mcp_server_id`)}</p>}
          </div>
          <div>
            <Label htmlFor={`tools_config.mcp_server_configs.${index}.api_key`} className="text-sm">API Key</Label>
            <Controller
              name={`tools_config.mcp_server_configs.${index}.api_key`}
              control={control}
              render={({ field }) => (
                <Input
                  id={`tools_config.mcp_server_configs.${index}.api_key`}
                  type="password"
                  {...field}
                  placeholder="Enter API Key"
                  className="mt-1"
                  aria-invalid={!!getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.api_key`)}
                />
              )}
            />
            {getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.api_key`) && 
             <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.api_key`)}</p>}
          </div>
           <div>
              <Label htmlFor={`tools_config.mcp_server_configs.${index}.config`} className="text-sm">Specific Config (JSON, optional)</Label>
              <Controller
                name={`tools_config.mcp_server_configs.${index}.config`}
                control={control}
                render={({ field }) => (
                  <Textarea
                    id={`tools_config.mcp_server_configs.${index}.config`}
                    value={field.value && typeof field.value === 'object' ? JSON.stringify(field.value, null, 2) : ''}
                    onChange={(e) => {
                      try {
                        const parsed = JSON.parse(e.target.value || '{}');
                        field.onChange(parsed);
                      } catch {
                        field.onChange(e.target.value);
                      }
                    }}
                    placeholder='{ \"parameter\": \"value\" }'
                    className="mt-1 font-mono text-sm h-24"
                    aria-invalid={!!getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.config`)}
                  />
                )}
              />
              {getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.config`) && 
               <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, `tools_config.mcp_server_configs.${index}.config`)}</p>}
            </div>
        </div>
      ))}
      <Button type="button" variant="outline" onClick={() => appendTool({ mcp_server_id: '', api_key: '', config: {} })}>
        <Plus className="h-4 w-4 mr-2" /> Add Tool
      </Button>
    </div>
     {getNestedErrorMessage(errors, 'tools_config.mcp_server_configs') && 
      <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'tools_config.mcp_server_configs')}</p>}
     {getNestedErrorMessage(errors, 'tools_config') && 
      <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'tools_config')}</p>}
  </Card>
);

export default ToolConfig; 