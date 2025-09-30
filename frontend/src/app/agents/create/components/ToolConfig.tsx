import React from "react";
import { Cpu, ArrowRight } from "lucide-react";
import { FieldErrors, UseFieldArrayReturn, UseFieldArrayAppend } from 'react-hook-form';
import { getNestedErrorMessage } from "../utils/formUtils";
import type { AgentFormValues, BuiltinToolConfig } from "../types";
import type { components } from '@/api/schema';
import { useState, useEffect, useMemo } from "react";
import { TriggerControl } from "./TriggerControl";
import { Accordion } from "@/components/ui/accordion";
import { SelectableList } from "./SelectableList";
import { useTranslations } from "next-intl";
import ConfigSheet from "./ConfigSheet";
import { Button } from "@/components/ui/button";
import { toast } from "sonner";
import { createMCPServerInstance, checkMCPServerInstanceConfiguration, getMCPServerInstance, updateMCPServerInstance } from "@/lib/api";
import { MCPInstanceConfigForm } from "@/components/MCPInstanceConfigForm";
import AccordionControl from "./AccordionControl";
import FormLabel from "@/components/FormLabel/FormLabel";

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

  // Configure server overlay (like marketplace, but in sheet)
  const [configureServerSheetOpen, setConfigureServerSheetOpen] = useState(false);
  const [selectedServer, setSelectedServer] = useState<MCPServer | null>(null);
  const [isEditingInstance, setIsEditingInstance] = useState(false);
  const [editingInstanceId, setEditingInstanceId] = useState<string | null>(null);
  const [instanceName, setInstanceName] = useState("");
  const [instanceDescription, setInstanceDescription] = useState("");
  const [envVars, setEnvVars] = useState<Record<string, string>>({});
  const [isChecking, setIsChecking] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [validationResult, setValidationResult] = useState<{ valid: boolean; errors: string[]; warnings: string[] } | null>(null);

  // Keep a local copy of active instances so the list updates immediately after creation
  const [activeInstances, setActiveInstances] = useState<any[]>(mcpInstanceList || []);
  useEffect(() => {
    setActiveInstances(mcpInstanceList || []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(mcpInstanceList)]);


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

  const handleAddConfigurationTools = (server: MCPServer) => {
    setSelectedServer(server);
    setIsEditingInstance(false);
    setEditingInstanceId(null);
    const defaultName = `${server.name} Instance`;
    const defaultDescription = `Instance of ${server.name}`;
    setInstanceName(defaultName);
    setInstanceDescription(defaultDescription);
    const initialEnv: Record<string, string> = {};
    (server.env_schema || []).forEach((envVar: any) => {
      const name = (envVar && (envVar.name as string)) || "";
      if (!name) return;
      const defVal = (envVar.default as string | undefined) || "";
      initialEnv[name] = defVal;
    });
    setEnvVars(initialEnv);
    setValidationResult(null);
    setConfigureServerSheetOpen(true);
  };

  const editTool = async (index: number) => {
    const tool = toolFields[index];
    if (!tool) return;
    try {
      const instanceId = tool.mcp_server_id as unknown as string;
      const { data: instance, error } = await getMCPServerInstance(instanceId);
      if (error || !instance) {
        toast.error('Failed to load instance for editing');
        return;
      }
      const serverSpec = mcpServers.find((s) => s.id === (instance as any).server_spec_id) || null;
      if (!serverSpec) {
        toast.error('Server specification not found');
        return;
      }
      setSelectedServer(serverSpec);
      setIsEditingInstance(true);
      setEditingInstanceId(instanceId);
      setInstanceName((instance as any).name || '');
      setInstanceDescription((instance as any).description || '');
      const env = ((instance as any).json_spec?.environment as Record<string, string>) || {};
      setEnvVars(env);
      setValidationResult(null);
      setConfigureServerSheetOpen(true);
    } catch (e) {
      console.error(e);
      toast.error('Could not open edit form');
    }
  };

  useEffect(() => {
    if (isSheetOpen && scrollToolId) {
      const timer = setTimeout(() => {
        const el = document.getElementById(`active-mcp-${scrollToolId}`) || document.getElementById(`mcp-${scrollToolId}`);
        el?.scrollIntoView({ behavior: 'smooth', block: 'center' });
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [isSheetOpen, scrollToolId]);

  const note = useMemo(() => (
    <>
      <p>Add MCP servers to enable tools for your agent.</p>
      <p>You can add multiple servers and configure them individually.</p>
    </>
  ), []);

  const title = useMemo(() => (
    <div className="flex items-center gap-2">
      <FormLabel icon={Cpu} className="cursor-pointer">Agent Tools</FormLabel>
    </div>
  ), []);

  return (
    <>
      {/* Builtin Tools Section */}
      {/**
       * <Card>
       *   <CardHeader>
       *     <CardTitle className="flex items-center gap-2">
       *       <Calculator className="h-4 w-4" />
       *       Tools Configuration
       *     </CardTitle>
       *   </CardHeader>
       *   <CardContent>
       *     <BuiltinToolIconGrid
       *       builtinTools={builtinTools}
       *       selectedTools={getSelectedBuiltinTools()}
       *       onAddTool={handleAddBuiltinTool}
       *       onRemoveTool={handleRemoveBuiltinTool}
       *       onUpdateToolConfig={handleUpdateBuiltinToolConfig}
       *       loading={loadingBuiltinTools}
       *     />
       *   </CardContent>
       * </Card>
       */}

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
            className="ml-auto"
            open={isSheetOpen}
            onOpenChange={setIsSheetOpen}
          >
            <div className="flex flex-col overflow-y-auto space-y-4">
              <div className="font-semibold">Active MCP Servers</div>
              <SelectableList
                items={activeInstances}
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
                disableExpand={true}
                items={mcpServers}
                prefix="mcp"
                extractTitle={(server) => server.name}
                onAdd={(server) => handleAddConfigurationTools(server)}
                onRemove={(server) => handleRemoveTool(server.id)}
                selectedIds={toolFields.map((item) => item.mcp_server_id)}
                openItemId={scrollToolId}
                inactiveLabel={<>Configure <ArrowRight className="h-3 w-3" /></>}
                renderContent={() => (
                  <div className="p-4 text-sm text-muted-foreground">Available</div>
                )}
              />
            </div>
          </ConfigSheet>
        }
      >
        <div className="space-y-4">
          {toolFields.length > 0 ? (
            <Accordion type="multiple" id="mcp-tools-items" className="space-y-2">
              {toolFields.map((item, index) => (
                <TriggerControl 
                  name={`tools_config.mcp_server_configs.${index}.mcp_server_id`}
                  enabledName={`tools_config.mcp_server_configs.${index}.enabled`}
                  key={`tool-${index}`}
                  trigger={
                    activeInstances.find((option: any) => option.id === item.mcp_server_id) ||
                    mcpServers.find((option) => option.id === item.mcp_server_id) ||
                    undefined
                  }
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
      </AccordionControl>

      {getNestedErrorMessage(errors, 'tools_config.mcp_server_configs') && 
        <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'tools_config.mcp_server_configs')}</p>}
      {getNestedErrorMessage(errors, 'tools_config.builtin_tools') && 
        <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'tools_config.builtin_tools')}</p>}
      {getNestedErrorMessage(errors, 'tools_config') && 
        <p className="text-sm text-red-500 mt-1">{getNestedErrorMessage(errors, 'tools_config')}</p>}

      {/* Configure Server Sheet overlay */}
      <ConfigSheet
        className="md:min-w-[500px]"
        title={selectedServer ? `${isEditingInstance ? 'Edit' : 'Configure'} ${selectedServer.name} Instance` : 'Configure MCP Server'}
        description={selectedServer?.description || ''}
        triggerClassName="hidden"
        open={configureServerSheetOpen}
        onOpenChange={setConfigureServerSheetOpen}
      >
        {selectedServer && (
          <div className="flex flex-col gap-4 overflow-y-auto pb-4">
            <MCPInstanceConfigForm
              renderAsForm={false}
              server={selectedServer}
              instanceName={instanceName}
              instanceDescription={instanceDescription}
              envVars={envVars}
              onChangeName={setInstanceName}
              onChangeDescription={setInstanceDescription}
              onChangeEnvVar={(name, value) => { setEnvVars((prev) => ({ ...prev, [name]: value })); if (validationResult) setValidationResult(null); }}
              onValidate={async () => { if (!selectedServer) return; setIsChecking(true); try { const check = await checkMCPServerInstanceConfiguration({ json_spec: { image: selectedServer.docker_image_url, port: 8000, environment: envVars } }); if (check.error) { toast.error('Failed to validate configuration'); } else { setValidationResult(check.data); if (check.data.valid) toast.success('Configuration is valid!'); else toast.warning(`Configuration has ${check.data.errors.length} error(s)`); } } catch (err) { console.error(err); toast.error('Validation failed'); } finally { setIsChecking(false); } }}
              onForceCreate={isEditingInstance ? undefined : async () => { if (!selectedServer) return; setIsCreating(true); try { const res = await createMCPServerInstance({ name: instanceName, description: instanceDescription, server_spec_id: selectedServer.id, json_spec: { image: selectedServer.docker_image_url, port: 8000, environment: envVars } }); if (res.error) throw new Error(typeof res.error.detail === 'string' ? res.error.detail : 'Failed to create instance'); toast.success(`Successfully created ${instanceName}`); if (res.data?.id) { setActiveInstances((prev) => { const exists = prev.some((i) => i.id === res.data!.id); return exists ? prev : [res.data!, ...prev]; }); appendTool([{ mcp_server_id: res.data.id, allowed_tools: [] } as any]); } setConfigureServerSheetOpen(false); } catch (err: any) { console.error(err); toast.error(err?.message || 'Failed to create instance'); } finally { setIsCreating(false); } }}
              onSubmit={async () => { if (!selectedServer) return; if (!isEditingInstance) { if (!validationResult) { toast.warning('Please validate the configuration first'); return; } if (validationResult && !validationResult.valid) { toast.error('Configuration validation failed. Use "Force Create" to proceed.'); return; } } setIsCreating(true); try { if (isEditingInstance && editingInstanceId) { const payload = { name: instanceName, description: instanceDescription, json_spec: { image: selectedServer.docker_image_url, port: 8000, environment: envVars } } as any; const { error } = await updateMCPServerInstance(editingInstanceId, payload); if (error) throw new Error(typeof (error as any).detail === 'string' ? (error as any).detail : 'Failed to update instance'); toast.success(`Successfully updated ${instanceName}`); setActiveInstances((prev) => prev.map((i: any) => i.id === editingInstanceId ? { ...i, name: instanceName, description: instanceDescription, json_spec: payload.json_spec } : i)); } else { const res = await createMCPServerInstance({ name: instanceName, description: instanceDescription, server_spec_id: selectedServer.id, json_spec: { image: selectedServer.docker_image_url, port: 8000, environment: envVars } }); if (res.error) throw new Error(typeof res.error.detail === 'string' ? res.error.detail : 'Failed to create instance'); toast.success(`Successfully created ${instanceName}`); if (res.data?.id) { setActiveInstances((prev) => { const exists = prev.some((i) => i.id === res.data!.id); return exists ? prev : [res.data!, ...prev]; }); appendTool([{ mcp_server_id: res.data.id, allowed_tools: [] } as any]); } } setConfigureServerSheetOpen(false); setIsEditingInstance(false); setEditingInstanceId(null); } catch (err: any) { console.error(err); toast.error(err?.message || (isEditingInstance ? 'Failed to update instance' : 'Failed to create instance')); } finally { setIsCreating(false); } }}
              submitDisabled={isCreating || !instanceName.trim() || (!isEditingInstance && (validationResult ? !validationResult.valid : false))}
              validateDisabled={isChecking || !instanceName.trim()}
              forceCreateDisabled={isEditingInstance || isCreating || !instanceName.trim()}
              submitLabel={isCreating ? (isEditingInstance ? 'Updating...' : 'Creating...') : (isEditingInstance ? 'Update Instance' : 'Create Instance')}
              extraActions={(
                <Button
                  variant="outline"
                  onClick={() => setConfigureServerSheetOpen(false)}
                  disabled={isCreating}
                  type="button"
                >
                  Cancel
                </Button>
              )}
            />
          </div>
        )}
      </ConfigSheet>
    </>
  );
};

export default ToolConfig; 