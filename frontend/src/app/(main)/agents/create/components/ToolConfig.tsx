import React, { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import Image from "next/image";
import { ArrowRight, Wrench } from "lucide-react";
import {
  FieldErrors,
  UseFieldArrayAppend,
  UseFieldArrayReturn,
} from "react-hook-form";
import { toast } from "sonner";
import type { components } from "@/api/schema";
import FormLabel from "@/components/FormLabel/FormLabel";
import { MCPInstanceConfigForm } from "@/components/MCPInstanceConfigForm";
import { Accordion } from "@/components/ui/accordion";
import { Button } from "@/components/ui/button";
import {
  checkMCPServerInstanceConfiguration,
  createMCPServerInstance,
  getMCPServerInstance,
  updateMCPServerInstance,
} from "@/lib/browser-api";
import type { AgentFormValues } from "../types";
import { getBuiltinToolDisplayInfo } from "../utils/builtinToolUtils";
import { getNestedErrorMessage } from "../utils/formUtils";
import AccordionControl from "./AccordionControl";
import ConfigSheet from "./ConfigSheet";
import { MethodsList } from "./MethodsList";
import { SelectableList } from "./SelectableList";
import { TriggerControl } from "./TriggerControl";

type MCPServer = components["schemas"]["MCPServerResponse"];

type ToolConfigProps = {
  control: any;
  setValue: any;
  errors: FieldErrors<AgentFormValues>;
  toolFields: UseFieldArrayReturn<
    AgentFormValues,
    "tools_config.mcp_server_configs",
    "id"
  >["fields"];
  removeTool: (index: number) => void;
  appendTool: UseFieldArrayAppend<
    AgentFormValues,
    "tools_config.mcp_server_configs"
  >;
  mcpServers: MCPServer[];
  mcpInstanceList: any[];
  builtinTools: any[];
  builtinToolFields?: UseFieldArrayReturn<
    AgentFormValues,
    "tools_config.builtin_tools",
    "id"
  >["fields"];
  removeBuiltinTool?: (index: number) => void;
  appendBuiltinTool?: UseFieldArrayAppend<
    AgentFormValues,
    "tools_config.builtin_tools"
  >;
};

const ToolConfig = ({
  control,
  setValue,
  errors,
  toolFields,
  removeTool,
  appendTool,
  mcpServers,
  mcpInstanceList,
  builtinTools,
  builtinToolFields,
  removeBuiltinTool,
  appendBuiltinTool,
}: ToolConfigProps) => {
  const [accordionValue, setAccordionValue] = useState<string>("tools");
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const [scrollToolId, setScrollToolId] = useState<string | null>(null);
  const [scrollBuiltinToolId, setScrollBuiltinToolId] = useState<string | null>(
    null
  );
  const [loadingBuiltinTools, setLoadingBuiltinTools] = useState(false);
  const [selectedMethods, setSelectedMethods] = useState<
    Record<string, Record<string, boolean>>
  >({});
  const t = useTranslations("AgentsPage");

  // Configure server overlay (like marketplace, but in sheet)
  const [configureServerSheetOpen, setConfigureServerSheetOpen] =
    useState(false);
  const [selectedServer, setSelectedServer] = useState<MCPServer | null>(null);
  const [isEditingInstance, setIsEditingInstance] = useState(false);
  const [editingInstanceId, setEditingInstanceId] = useState<string | null>(
    null
  );
  const [instanceName, setInstanceName] = useState("");
  const [instanceDescription, setInstanceDescription] = useState("");
  const [envVars, setEnvVars] = useState<Record<string, string>>({});
  const [isChecking, setIsChecking] = useState(false);
  const [isCreating, setIsCreating] = useState(false);
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    errors: string[];
    warnings: string[];
  } | null>(null);

  // Keep a local copy of active instances so the list updates immediately after creation
  const [activeInstances, setActiveInstances] = useState<any[]>(
    mcpInstanceList || []
  );
  useEffect(() => {
    setActiveInstances(mcpInstanceList || []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(mcpInstanceList)]);

  // Initialize selectedMethods for sheet (all methods selected by default)
  useEffect(() => {
    if (!builtinTools?.length) return;

    const toolsMethods = builtinTools.reduce(
      (acc, tool) => {
        if (tool.available_methods) {
          acc[tool.name] = tool.available_methods.reduce(
            (methods: Record<string, boolean>, method: any) => {
              methods[method.name] = true;
              return methods;
            },
            {} as Record<string, boolean>
          );
        }
        return acc;
      },
      {} as Record<string, Record<string, boolean>>
    );

    setSelectedMethods(toolsMethods);
  }, [builtinTools]);

  const handleAddBuiltinTool = (toolName: string) => {
    if (
      !appendBuiltinTool ||
      builtinToolFields?.some((field) => field.tool_name === toolName)
    )
      return;

    const currentState = selectedMethods[toolName];
    const tool = builtinTools.find((t) => t.name === toolName);

    if (currentState && tool?.available_methods) {
      const disabledMethods = tool.available_methods
        .filter((method: any) => currentState[method.name] === false)
        .reduce(
          (acc: Record<string, boolean>, method: any) => {
            acc[method.name] = false;
            return acc;
          },
          {} as Record<string, boolean>
        );

      appendBuiltinTool({
        tool_name: toolName,
        disabled_methods:
          Object.keys(disabledMethods).length > 0 ? disabledMethods : undefined,
      });
    } else {
      // Initialize selectedMethods for this tool if not already set
      if (tool?.available_methods && !currentState) {
        const initialMethods = tool.available_methods.reduce(
          (acc: Record<string, boolean>, method: any) => {
            acc[method.name] = true;
            return acc;
          },
          {} as Record<string, boolean>
        );

        setSelectedMethods((prev) => ({
          ...prev,
          [toolName]: initialMethods,
        }));
      }

      appendBuiltinTool({ tool_name: toolName });
    }
  };

  const handleRemoveBuiltinTool = (toolName: string) => {
    if (!removeBuiltinTool) return;

    const index = builtinToolFields?.findIndex(
      (field) => field.tool_name === toolName
    );
    if (index !== undefined && index !== -1) {
      removeBuiltinTool(index);
    }
  };

  const handleMethodToggle = (
    toolName: string,
    methodName: string,
    checked: boolean
  ) => {
    setSelectedMethods((prev) => ({
      ...prev,
      [toolName]: {
        ...prev[toolName],
        [methodName]: checked,
      },
    }));

    const currentIndex = builtinToolFields?.findIndex(
      (field) => field.tool_name === toolName
    );
    if (
      currentIndex === undefined ||
      currentIndex === -1 ||
      !builtinToolFields ||
      !setValue
    )
      return;

    const field = builtinToolFields[currentIndex];
    const newDisabledMethods = { ...(field.disabled_methods || {}) };

    if (checked) {
      delete newDisabledMethods[methodName];
    } else {
      newDisabledMethods[methodName] = false;
    }

    // Update the existing field instead of removing and adding
    setValue(
      `tools_config.builtin_tools.${currentIndex}.disabled_methods`,
      Object.keys(newDisabledMethods).length > 0
        ? newDisabledMethods
        : undefined
    );
  };

  const getSelectedBuiltinTools = () =>
    builtinToolFields?.map((field) => ({
      tool_name: field.tool_name,
      disabled_methods: field.disabled_methods || {},
    })) || [];

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
        toast.error("Failed to load instance for editing");
        return;
      }
      const serverSpec =
        mcpServers.find((s) => s.id === (instance as any).server_spec_id) ||
        null;
      if (!serverSpec) {
        toast.error("Server specification not found");
        return;
      }
      setSelectedServer(serverSpec);
      setIsEditingInstance(true);
      setEditingInstanceId(instanceId);
      setInstanceName((instance as any).name || "");
      setInstanceDescription((instance as any).description || "");
      const env =
        ((instance as any).json_spec?.environment as Record<string, string>) ||
        {};
      setEnvVars(env);
      setValidationResult(null);
      setConfigureServerSheetOpen(true);
    } catch (e) {
      console.error(e);
      toast.error("Could not open edit form");
    }
  };

  useEffect(() => {
    if (isSheetOpen && scrollToolId) {
      const timer = setTimeout(() => {
        const el =
          document.getElementById(`active-mcp-${scrollToolId}`) ||
          document.getElementById(`mcp-${scrollToolId}`);
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [isSheetOpen, scrollToolId]);

  useEffect(() => {
    if (isSheetOpen && scrollBuiltinToolId) {
      const timer = setTimeout(() => {
        const el = document.getElementById(
          `builtin-tool-${scrollBuiltinToolId}`
        );
        el?.scrollIntoView({ behavior: "smooth", block: "center" });
      }, 100);
      return () => clearTimeout(timer);
    }
  }, [isSheetOpen, scrollBuiltinToolId]);

  const note = useMemo(
    () => (
      <>
        <p>{t("create.agentToolsDescription")}</p>
        <p>{t("create.agentToolsNote")}</p>
      </>
    ),
    []
  );

  const title = useMemo(
    () => (
      <FormLabel icon={Wrench} className="cursor-pointer">
        {t("create.agentTools")}
      </FormLabel>
    ),
    []
  );

  return (
    <>
      {/* Builtin Tools Section */}

      {/* <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              Tools Configuration
            </CardTitle>
          </CardHeader>
          <CardContent>
            <BuiltinToolIconGrid
              builtinTools={builtinTools}
              selectedTools={getSelectedBuiltinTools()}
              onAddTool={handleAddBuiltinTool}
              onRemoveTool={handleRemoveBuiltinTool}
              onUpdateToolConfig={() => console.log('update tool config')}
              loading={loadingBuiltinTools}
            />
          </CardContent>
        </Card> */}

      <AccordionControl
        id="tools"
        accordionValue={accordionValue}
        setAccordionValue={setAccordionValue}
        title={title}
        note={note}
        mainControl={
          <ConfigSheet
            title={t("create.toolsMcp")}
            description={t("create.toolsMcpDescription")}
            triggerText={t("create.tool")}
            className="ml-auto"
            open={isSheetOpen}
            onOpenChange={setIsSheetOpen}
          >
            <div className="flex flex-col space-y-4 overflow-y-auto">
              <div className="font-semibold">{t("create.builtinTools")}</div>
              <SelectableList
                items={builtinTools.map((tool) => ({ ...tool, id: tool.name }))}
                prefix="builtin-tool"
                extractTitle={(tool) => {
                  const { IconComponent, displayName } =
                    getBuiltinToolDisplayInfo(tool);
                  return (
                    <div className="flex flex-row items-center gap-2 px-[7px] py-[7px]">
                      <IconComponent className="h-5 w-5 text-muted-foreground" />
                      <h3 className="text-sm font-medium transition-colors duration-300 group-hover:text-accent group-data-[state=open]:text-accent dark:group-hover:text-accent dark:group-data-[state=open]:text-accent">
                        {displayName}
                      </h3>
                    </div>
                  );
                }}
                onAdd={(tool) => handleAddBuiltinTool(tool.name)}
                onRemove={(tool) => handleRemoveBuiltinTool(tool.name)}
                selectedIds={getSelectedBuiltinTools().map(
                  (tool) => tool.tool_name
                )}
                openItemId={scrollBuiltinToolId}
                renderContent={(tool) => {
                  const methodsState = selectedMethods[tool.name] || {};

                  return (
                    <div className="space-y-2 p-2">
                      <p className="text-xs text-muted-foreground">
                        {tool.description}
                      </p>
                      <MethodsList
                        methods={tool.available_methods || []}
                        selectedMethods={methodsState}
                        onMethodToggle={(methodName, checked) =>
                          handleMethodToggle(tool.name, methodName, checked)
                        }
                        toolName={tool.name}
                        showSelectAll={true}
                        onSelectAll={(checked) => {
                          if (tool.available_methods) {
                            tool.available_methods.forEach((method: any) => {
                              handleMethodToggle(
                                tool.name,
                                method.name,
                                checked
                              );
                            });
                          }
                        }}
                      />
                    </div>
                  );
                }}
              />
              <div className="flex items-center gap-2 font-semibold">
                <Image
                  src="/mcp.svg"
                  alt="MCP"
                  width={16}
                  height={16}
                  className="text-current"
                />
                {t("create.activeMcpServers")}
              </div>
              <SelectableList
                items={activeInstances}
                prefix="active-mcp"
                extractTitle={(instance) => (
                  <div className="flex min-w-0 flex-row items-center gap-2 px-[7px] py-[7px]">
                    <div className="relative shrink-0">
                      <img src="/Icon.svg" alt="" className="h-5 w-5" />
                    </div>
                    <h3 className="truncate text-sm font-medium transition-colors duration-300 group-hover:text-accent group-data-[state=open]:text-accent dark:group-hover:text-accent dark:group-data-[state=open]:text-accent">
                      {instance.name || instance.id}
                    </h3>
                  </div>
                )}
                onAdd={(instance) => handleAddTools([instance])}
                onRemove={(instance) => handleRemoveTool(instance.id)}
                selectedIds={toolFields.map((item) => item.mcp_server_id)}
                openItemId={scrollToolId}
                renderContent={(instance) => (
                  <div className="space-y-2 p-2">
                    <p className="text-xs text-muted-foreground">
                      Active MCP Server Instance
                    </p>
                    {instance.available_tools &&
                      instance.available_tools.length > 0 && (
                        <div className="space-y-1">
                          <p className="text-xs font-medium text-foreground">
                            Available Tools:
                          </p>
                          <div className="space-y-1">
                            {instance.available_tools.map((tool: any) => (
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
                      )}
                  </div>
                )}
              />
              <div className="flex items-center gap-2 font-semibold">
                <Image
                  src="/mcp.svg"
                  alt="MCP"
                  width={16}
                  height={16}
                  className="text-current"
                />
                {t("create.availableMcpServers")}
              </div>
              <SelectableList
                disableExpand={true}
                items={mcpServers}
                prefix="mcp"
                extractTitle={(server) => (
                  <div className="flex min-w-0 flex-row items-center gap-2 px-[7px] py-[7px]">
                    <div className="relative shrink-0">
                      <img src="/Icon.svg" alt="" className="h-5 w-5" />
                    </div>
                    <h3 className="truncate text-sm font-medium transition-colors duration-300 group-hover:text-accent group-data-[state=open]:text-accent dark:group-hover:text-accent dark:group-data-[state=open]:text-accent">
                      {server.name}
                    </h3>
                  </div>
                )}
                onAdd={(server) => handleAddConfigurationTools(server)}
                onRemove={(server) => handleRemoveTool(server.id)}
                selectedIds={toolFields.map((item) => item.mcp_server_id)}
                openItemId={scrollToolId}
                inactiveLabel={
                  <>
                    Configure <ArrowRight className="h-3 w-3" />
                  </>
                }
                renderContent={(server) => (
                  <div className="space-y-2 p-2">
                    <p className="text-xs text-muted-foreground">
                      {server.description || "Available MCP Server"}
                    </p>
                    {(server as any).available_tools &&
                      (server as any).available_tools.length > 0 && (
                        <div className="space-y-1">
                          <p className="text-xs font-medium text-foreground">
                            Available Tools:
                          </p>
                          <div className="space-y-1">
                            {(server as any).available_tools.map(
                              (tool: any) => (
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
                              )
                            )}
                          </div>
                        </div>
                      )}
                  </div>
                )}
              />
            </div>
          </ConfigSheet>
        }
      >
        <div className="space-y-4">
          {/* Built-in Tools Section */}
          {builtinToolFields && builtinToolFields.length > 0 && (
            <div className="space-y-2">
              <h4 className="text-sm font-medium text-foreground">
                {t("create.builtinTools")}
              </h4>
              <Accordion
                type="multiple"
                id="builtin-tools-items"
                className="space-y-2"
              >
                {builtinToolFields.map((item, index) => {
                  const builtinTool = builtinTools.find(
                    (tool) => tool.name === item.tool_name
                  );
                  if (!builtinTool) return null;

                  const { IconComponent, displayName, description } =
                    getBuiltinToolDisplayInfo(builtinTool);

                  return (
                    <TriggerControl
                      name={`tools_config.builtin_tools.${index}.tool_name`}
                      enabledName={`tools_config.builtin_tools.${index}.enabled`}
                      key={`builtin-tool-${index}`}
                      trigger={{
                        id: builtinTool.name,
                        name: displayName,
                        description: description,
                        icon: IconComponent,
                        available_methods: builtinTool.available_methods,
                      }}
                      index={index}
                      control={control}
                      removeEvent={() => removeBuiltinTool?.(index)}
                      // editEvent={() => {}}
                      selectedMethods={selectedMethods[builtinTool.name] || {}}
                      onMethodToggle={(methodName: string, checked: boolean) =>
                        handleMethodToggle(
                          builtinTool.name,
                          methodName,
                          checked
                        )
                      }
                    />
                  );
                })}
              </Accordion>
            </div>
          )}

          {/* MCP Tools Section */}
          {toolFields.length > 0 ? (
            <div className="space-y-2">
              <h4 className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Image
                  src="/mcp.svg"
                  alt="MCP"
                  width={14}
                  height={14}
                  className="text-current"
                />
                {t("create.mcpServers")}
              </h4>
              <Accordion
                type="multiple"
                id="mcp-tools-items"
                className="space-y-2"
              >
                {toolFields.map((item, index) => (
                  <TriggerControl
                    name={`tools_config.mcp_server_configs.${index}.mcp_server_id`}
                    enabledName={`tools_config.mcp_server_configs.${index}.enabled`}
                    key={`tool-${index}`}
                    trigger={
                      activeInstances.find(
                        (option: any) => option.id === item.mcp_server_id
                      ) ||
                      mcpServers.find(
                        (option) => option.id === item.mcp_server_id
                      ) ||
                      undefined
                    }
                    index={index}
                    control={control}
                    removeEvent={() => removeTool(index)}
                    editEvent={() => editTool(index)}
                  />
                ))}
              </Accordion>
            </div>
          ) : (
            <div className="mt-2 cursor-default items-center gap-2 rounded-md border p-3 text-center text-xs text-muted-foreground/50">
              {t("create.agentToolsDescription")}
              <p>{t("create.agentToolsNote")}</p>
            </div>
          )}
        </div>
      </AccordionControl>

      {getNestedErrorMessage(errors, "tools_config.mcp_server_configs") && (
        <p className="mt-1 text-sm text-red-500">
          {getNestedErrorMessage(errors, "tools_config.mcp_server_configs")}
        </p>
      )}
      {getNestedErrorMessage(errors, "tools_config.builtin_tools") && (
        <p className="mt-1 text-sm text-red-500">
          {getNestedErrorMessage(errors, "tools_config.builtin_tools")}
        </p>
      )}
      {getNestedErrorMessage(errors, "tools_config") && (
        <p className="mt-1 text-sm text-red-500">
          {getNestedErrorMessage(errors, "tools_config")}
        </p>
      )}

      {/* Configure Server Sheet overlay */}
      <ConfigSheet
        className="md:min-w-[500px]"
        title={
          selectedServer
            ? `${isEditingInstance ? "Edit" : "Configure"} ${selectedServer.name} Instance`
            : "Configure MCP Server"
        }
        description={selectedServer?.description || ""}
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
              onChangeEnvVar={(name, value) => {
                setEnvVars((prev) => ({ ...prev, [name]: value }));
                if (validationResult) setValidationResult(null);
              }}
              onValidate={async () => {
                if (!selectedServer) return;
                setIsChecking(true);
                try {
                  const check = await checkMCPServerInstanceConfiguration({
                    json_spec: {
                      image: selectedServer.docker_image_url,
                      port: 8000,
                      environment: envVars,
                    },
                  });
                  if (check.error) {
                    toast.error("Failed to validate configuration");
                  } else {
                    const validationData = check.data as any;
                    setValidationResult(validationData);
                    if (validationData?.valid)
                      toast.success("Configuration is valid!");
                    else
                      toast.warning(
                        `Configuration has ${validationData?.errors?.length || 0} error(s)`
                      );
                  }
                } catch (err) {
                  console.error(err);
                  toast.error("Validation failed");
                } finally {
                  setIsChecking(false);
                }
              }}
              onForceCreate={
                isEditingInstance
                  ? undefined
                  : async () => {
                      if (!selectedServer) return;
                      setIsCreating(true);
                      try {
                        const res = await createMCPServerInstance({
                          name: instanceName,
                          description: instanceDescription,
                          server_spec_id: selectedServer.id,
                          json_spec: {
                            image: selectedServer.docker_image_url,
                            port: 8000,
                            environment: envVars,
                          },
                        });
                        if (res.error)
                          throw new Error(
                            typeof res.error.detail === "string"
                              ? res.error.detail
                              : "Failed to create instance"
                          );
                        toast.success(`Successfully created ${instanceName}`);
                        if (res.data?.id) {
                          setActiveInstances((prev) => {
                            const exists = prev.some(
                              (i) => i.id === res.data!.id
                            );
                            return exists ? prev : [res.data!, ...prev];
                          });
                          appendTool([
                            {
                              mcp_server_id: res.data.id,
                              allowed_tools: [],
                            } as any,
                          ]);
                        }
                        setConfigureServerSheetOpen(false);
                      } catch (err: any) {
                        console.error(err);
                        toast.error(
                          err?.message || "Failed to create instance"
                        );
                      } finally {
                        setIsCreating(false);
                      }
                    }
              }
              onSubmit={async () => {
                if (!selectedServer) return;
                if (!isEditingInstance) {
                  if (!validationResult) {
                    toast.warning("Please validate the configuration first");
                    return;
                  }
                  if (validationResult && !validationResult.valid) {
                    toast.error(
                      'Configuration validation failed. Use "Force Create" to proceed.'
                    );
                    return;
                  }
                }
                setIsCreating(true);
                try {
                  if (isEditingInstance && editingInstanceId) {
                    const payload = {
                      name: instanceName,
                      description: instanceDescription,
                      json_spec: {
                        image: selectedServer.docker_image_url,
                        port: 8000,
                        environment: envVars,
                      },
                    } as any;
                    const { error } = await updateMCPServerInstance(
                      editingInstanceId,
                      payload
                    );
                    if (error)
                      throw new Error(
                        typeof (error as any).detail === "string"
                          ? (error as any).detail
                          : "Failed to update instance"
                      );
                    toast.success(`Successfully updated ${instanceName}`);
                    setActiveInstances((prev) =>
                      prev.map((i: any) =>
                        i.id === editingInstanceId
                          ? {
                              ...i,
                              name: instanceName,
                              description: instanceDescription,
                              json_spec: payload.json_spec,
                            }
                          : i
                      )
                    );
                  } else {
                    const res = await createMCPServerInstance({
                      name: instanceName,
                      description: instanceDescription,
                      server_spec_id: selectedServer.id,
                      json_spec: {
                        image: selectedServer.docker_image_url,
                        port: 8000,
                        environment: envVars,
                      },
                    });
                    if (res.error)
                      throw new Error(
                        typeof res.error.detail === "string"
                          ? res.error.detail
                          : "Failed to create instance"
                      );
                    toast.success(`Successfully created ${instanceName}`);
                    if (res.data?.id) {
                      setActiveInstances((prev) => {
                        const exists = prev.some((i) => i.id === res.data!.id);
                        return exists ? prev : [res.data!, ...prev];
                      });
                      appendTool([
                        {
                          mcp_server_id: res.data.id,
                          allowed_tools: [],
                        } as any,
                      ]);
                    }
                  }
                  setConfigureServerSheetOpen(false);
                  setIsEditingInstance(false);
                  setEditingInstanceId(null);
                } catch (err: any) {
                  console.error(err);
                  toast.error(
                    err?.message ||
                      (isEditingInstance
                        ? "Failed to update instance"
                        : "Failed to create instance")
                  );
                } finally {
                  setIsCreating(false);
                }
              }}
              submitDisabled={
                isCreating ||
                !instanceName.trim() ||
                (!isEditingInstance &&
                  (validationResult ? !validationResult.valid : false))
              }
              validateDisabled={isChecking || !instanceName.trim()}
              forceCreateDisabled={
                isEditingInstance || isCreating || !instanceName.trim()
              }
              submitLabel={
                isCreating
                  ? isEditingInstance
                    ? "Updating..."
                    : "Creating..."
                  : isEditingInstance
                    ? "Update Instance"
                    : "Create Instance"
              }
              extraActions={
                <Button
                  variant="outline"
                  onClick={() => setConfigureServerSheetOpen(false)}
                  disabled={isCreating}
                  type="button"
                >
                  Cancel
                </Button>
              }
            />
          </div>
        )}
      </ConfigSheet>
    </>
  );
};

export default ToolConfig;
