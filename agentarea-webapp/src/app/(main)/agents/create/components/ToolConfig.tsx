import React, { useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import Image from "next/image";
import { ArrowRight, Globe, Wrench } from "lucide-react";
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
import Note from "@/components/ui/note";
import {
  checkMCPServerInstanceConfigurationAction as checkMCPServerInstanceConfiguration,
  createMCPServerInstanceAction as createMCPServerInstance,
  getMCPServerInstanceAction as getMCPServerInstance,
  updateMCPServerInstanceAction as updateMCPServerInstance,
} from "@/lib/server-actions";
import { listOpenAPIConnectionsAction as listOpenAPIConnections } from "@/lib/server-actions";
import { getMCPConnectionIconSrc } from "@/app/(main)/mcp-servers/utils";
import {
  McpAvailableTool,
  McpInstance,
  resolveMcpRef,
} from "@/lib/mcp/resolveMcpRef";
import type { OpenAPIConnection } from "@/app/(main)/mcp-servers/types";
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
  openapiFields?: UseFieldArrayReturn<
    AgentFormValues,
    "tools_config.openapi_configs",
    "id"
  >["fields"];
  removeOpenapiTool?: (index: number) => void;
  appendOpenapiTool?: UseFieldArrayAppend<
    AgentFormValues,
    "tools_config.openapi_configs"
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
  openapiFields,
  removeOpenapiTool,
  appendOpenapiTool,
}: ToolConfigProps) => {
  const [accordionValue, setAccordionValue] = useState<string>("tools");
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const [scrollToolId] = useState<string | null>(null);
  const [scrollBuiltinToolId] = useState<string | null>(
    null
  );
  const [selectedMethods, setSelectedMethods] = useState<
    Record<string, Record<string, boolean>>
  >({});
  const t = useTranslations("AgentsPage");
  const tMcp = useTranslations("MCPServersPage.createInstance");

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

  // OpenAPI connections state
  const [openapiConnections, setOpenapiConnections] = useState<OpenAPIConnection[]>([]);
  const [loadingOpenapiConnections, setLoadingOpenapiConnections] = useState(false);

  useEffect(() => {
    setLoadingOpenapiConnections(true);
    listOpenAPIConnections()
      .then(({ data }) => {
        const items = (data as any)?.items || data || [];
        setOpenapiConnections(Array.isArray(items) ? items : []);
      })
      .catch((err) => {
        console.error("Failed to load OpenAPI connections:", err);
      })
      .finally(() => {
        setLoadingOpenapiConnections(false);
      });
  }, []);

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

  const handleAddOpenapiConnection = (connection: OpenAPIConnection) => {
    if (!appendOpenapiTool) return;
    const alreadyAdded = openapiFields?.some(
      (f) => f.openapi_connection_id === connection.id
    );
    if (alreadyAdded) return;
    // Default new OpenAPI attachments to "searchable" — the catalog block in
    // the system prompt + load_tools meta-tool keeps token cost flat regardless
    // of spec size (issue #115). Existing entries without load_mode keep their
    // legacy "explicit" behavior.
    appendOpenapiTool({
      openapi_connection_id: connection.id,
      openapi_connection_name: connection.name,
      allowed_tools: [],
      load_mode: "searchable",
    });
  };

  const handleOpenapiLoadModeChange = (
    connectionId: string,
    mode: "explicit" | "searchable"
  ) => {
    if (!setValue || !openapiFields) return;
    const index = openapiFields.findIndex(
      (f) => f.openapi_connection_id === connectionId
    );
    if (index === -1) return;
    setValue(`tools_config.openapi_configs.${index}.load_mode`, mode);
  };

  const handleRemoveOpenapiConnection = (connectionId: string) => {
    if (!removeOpenapiTool) return;
    const index = openapiFields?.findIndex(
      (f) => f.openapi_connection_id === connectionId
    );
    if (index !== undefined && index !== -1) {
      removeOpenapiTool(index);
    }
  };

  const handleOpenapiToolToggle = (
    connectionId: string,
    toolName: string,
    enabled: boolean
  ) => {
    if (!setValue || !openapiFields) return;
    const index = openapiFields.findIndex(
      (f) => f.openapi_connection_id === connectionId
    );
    if (index === -1) return;

    const field = openapiFields[index];
    const connection = openapiConnections.find((c) => c.id === connectionId);
    const allToolNames = (connection?.available_tools || []).map((t) => t.name);

    // Empty allowed_tools means "all enabled" — initialize on first toggle
    let current: string[] = (field as any).allowed_tools || [];
    if (current.length === 0 && allToolNames.length > 0) {
      current = [...allToolNames];
    }

    let updated: string[];
    if (enabled) {
      updated = current.includes(toolName) ? current : [...current, toolName];
    } else {
      updated = current.filter((t) => t !== toolName);
    }

    setValue(
      `tools_config.openapi_configs.${index}.allowed_tools`,
      updated
    );
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

  // Resolve a connection icon the same way the /mcp-servers page does: the icon
  // usually lives on the server spec, so pair the instance with its spec.
  const instanceIconSrc = (instance: McpInstance): string | undefined => {
    const serverSpec = instance.server_spec_id
      ? mcpServers.find((s) => s.id === instance.server_spec_id)
      : undefined;
    return getMCPConnectionIconSrc(instance, serverSpec);
  };
  const serverIconSrc = (server: MCPServer): string | undefined =>
    getMCPConnectionIconSrc(server);

  // Tools discovered for an MCP instance (top-level `tools` from verification,
  // or json_spec.available_tools for older/bundle specs) — normalized by the
  // shared resolver.
  const getInstanceTools = (instance: McpInstance): McpAvailableTool[] => {
    const res = resolveMcpRef(instance.id, activeInstances, mcpServers);
    return res.status === "instance" ? res.availableTools : [];
  };

  // Agents reference an MCP by instance UUID (webapp flow) or instance name
  // (bundle installs); resolveMcpRef mirrors the runtime's id-then-name lookup.
  const resolveInstanceTrigger = (mcpServerId: string) => {
    const res = resolveMcpRef(mcpServerId, activeInstances, mcpServers);
    if (res.status === "instance") {
      return {
        id: res.instance.id,
        name: res.instance.name,
        description: res.instance.description ?? undefined,
        iconSrc: res.iconSrc,
        available_tools: res.availableTools,
      };
    }
    if (res.status === "server") {
      return {
        id: res.server.id,
        name: res.server.name,
        description: res.server.description ?? undefined,
        iconSrc: res.iconSrc,
        available_tools: [] as McpAvailableTool[],
      };
    }
    // Dangling ref (instance deleted, or never created by an old bundle
    // install). Render a neutral row instead of an error banner.
    return {
      id: mcpServerId,
      name: mcpServerId,
      label: mcpServerId,
      description: "",
      icon: Wrench,
      available_tools: [] as McpAvailableTool[],
    };
  };

  // Small mark used in the picker lists: real connection icon, or a wrench when
  // the registry has no icon for this server.
  const McpMark = ({ src }: { src?: string }) => (
    <span className="relative grid h-4 w-4 shrink-0 place-items-center overflow-hidden">
      {src ? (
        <img src={src} alt="" className="h-4 w-4 object-contain" />
      ) : (
        <Wrench className="h-4 w-4 text-muted-foreground" />
      )}
    </span>
  );

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
    setInstanceName(tMcp("defaults.name", { serverName: server.name }));
    setInstanceDescription(
      tMcp("defaults.description", { serverName: server.name })
    );
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
    [t]
  );

  const title = useMemo(
    () => (
      <FormLabel icon={Wrench} className="cursor-pointer">
        {t("create.agentTools")}
      </FormLabel>
    ),
    [t]
  );

  return (
    <>
      {/* Builtin Tools Section */}
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
              <div className="font-semibold text-sm">{t("create.builtinTools")}</div>
              <SelectableList
                items={builtinTools.map((tool) => ({ ...tool, id: tool.name }))}
                prefix="builtin-tool"
                extractTitle={(tool) => {
                  const { IconComponent, displayName } =
                    getBuiltinToolDisplayInfo(tool);
                  return (
                    <div className="flex flex-row items-center gap-2 px-[7px] py-[7px]">
                      <IconComponent className="h-4 w-4 text-muted-foreground" />
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
              <div className="flex items-center gap-2 font-semibold text-sm">
                <Globe className="h-4 w-4 text-muted-foreground" />
                {t("create.availableOpenAPIConnections")}
              </div>
              {loadingOpenapiConnections ? (
                <Note>
                  <p>Loading OpenAPI connections...</p>
                </Note>
              ) : openapiConnections.length > 0 ? (
                <SelectableList
                  items={openapiConnections}
                  prefix="openapi"
                  extractTitle={(connection) => (
                    <div className="flex min-w-0 flex-row items-center gap-1 px-[7px] py-[7px]">
                      <div className="relative shrink-0">
                        <Globe className="h-4 w-4 text-muted-foreground" />
                      </div>
                      <h3 className="truncate text-sm font-medium transition-colors duration-300 group-hover:text-accent group-data-[state=open]:text-accent dark:group-hover:text-accent dark:group-data-[state=open]:text-accent">
                        {connection.name}
                      </h3>
                    </div>
                  )}
                  onAdd={(connection) => handleAddOpenapiConnection(connection)}
                  onRemove={(connection) => handleRemoveOpenapiConnection(connection.id)}
                  selectedIds={(openapiFields || []).map((f) => f.openapi_connection_id)}
                  renderContent={(connection) => (
                    <div className="space-y-2 p-2">
                      <p className="text-xs text-muted-foreground">
                        {connection.base_url}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {connection.available_tools?.length ?? 0} operations available
                      </p>
                      {connection.available_tools && connection.available_tools.length > 0 && (
                        <div className="space-y-1">
                          <p className="text-xs font-medium text-foreground">Operations:</p>
                          <div className="space-y-1">
                            {connection.available_tools.map((tool) => {
                              const field = (openapiFields || []).find(
                                (f) => f.openapi_connection_id === connection.id
                              );
                              const allowedTools: string[] = (field as any)?.allowed_tools || [];
                              const isEnabled =
                                allowedTools.length === 0 ||
                                allowedTools.includes(tool.name);
                              const isSelected = (openapiFields || []).some(
                                (f) => f.openapi_connection_id === connection.id
                              );
                              return (
                                <div
                                  key={tool.name}
                                  className="flex items-center gap-2 rounded bg-muted/30 p-1"
                                >
                                  {isSelected && (
                                    <input
                                      type="checkbox"
                                      checked={isEnabled}
                                      onChange={(e) =>
                                        handleOpenapiToolToggle(
                                          connection.id,
                                          tool.name,
                                          e.target.checked
                                        )
                                      }
                                      className="h-3 w-3 shrink-0"
                                    />
                                  )}
                                  <span className="text-xs text-foreground">
                                    {tool.name}
                                  </span>
                                  {tool.description && (
                                    <span className="ml-auto text-xs text-muted-foreground truncate max-w-[120px]">
                                      {tool.description}
                                    </span>
                                  )}
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                />
              ) : (
                <Note>
                  <p>No OpenAPI connections configured yet.</p>
                </Note>
              )}
              <div className="flex items-center gap-2 font-semibold text-sm">
                <Image
                  src="/mcp.svg"
                  alt="MCP"
                  width={16}
                  height={16}
                  className="text-current"
                />
                {t("create.activeMcpServers")}
              </div>
              {activeInstances.length > 0 ? (
                <SelectableList
                  items={activeInstances}
                  prefix="active-mcp"
                  extractTitle={(instance) => (
                    <div className="flex min-w-0 flex-row items-center gap-1 px-[7px] py-[7px]">
                      <McpMark src={instanceIconSrc(instance)} />
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
                      {getInstanceTools(instance).length > 0 && (
                          <div className="space-y-1">
                            <p className="text-xs font-medium text-foreground">
                              Available Tools:
                            </p>
                            <div className="space-y-1">
                              {getInstanceTools(instance).map((tool: any) => (
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
              ) : (
                <Note>
                  <p>{t("create.noActiveMcpServersDescription")}</p>
                </Note>
              )}
              <div className="flex items-center gap-2 font-semibold text-sm">
                <Image
                  src="/mcp.svg"
                  alt="MCP"
                  width={16}
                  height={16}
                  className="text-current"
                />
                {t("create.availableMcpServers")}
              </div>
              {mcpServers.length > 0 ? (
                <SelectableList
                  disableExpand={true}
                  items={mcpServers}
                  prefix="mcp"
                  extractTitle={(server) => (
                    <div className="flex min-w-0 flex-row items-center gap-1 px-[7px] py-[7px]">
                      <McpMark src={serverIconSrc(server)} />
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
                    </div>
                  )}
                />
              ) : (
                <Note>
                  <p>{t("create.noAvailableMcpServersDescription")}</p>
                </Note>
              )}
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
          {toolFields.length > 0 && (
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
                    trigger={resolveInstanceTrigger(item.mcp_server_id)}
                    index={index}
                    control={control}
                    removeEvent={() => removeTool(index)}
                    editEvent={() => editTool(index)}
                    allowedToolsFieldName={`tools_config.mcp_server_configs.${index}.allowed_tools`}
                    onToolStateChange={(toolName, state) => {
                      const trigger = resolveInstanceTrigger(item.mcp_server_id);
                      const allTools = trigger?.available_tools || [];
                      let currentAllowed: any[] = (item as any).allowed_tools || [];

                      // Empty means "all enabled" — initialize with all tools on first toggle
                      if (currentAllowed.length === 0 && allTools.length > 0) {
                        currentAllowed = allTools.map((t: any) => ({ tool_name: t.name }));
                      }

                      let newAllowed: any[];
                      if (state === "disabled") {
                        newAllowed = currentAllowed.filter((t: any) => t.tool_name !== toolName);
                      } else {
                        const existing = currentAllowed.find((t: any) => t.tool_name === toolName);
                        if (existing) {
                          newAllowed = currentAllowed.map((t: any) =>
                            t.tool_name === toolName
                              ? { ...t, requires_user_confirmation: state === "approval_required" }
                              : t
                          );
                        } else {
                          newAllowed = [
                            ...currentAllowed,
                            { tool_name: toolName, requires_user_confirmation: state === "approval_required" },
                          ];
                        }
                      }
                      setValue(`tools_config.mcp_server_configs.${index}.allowed_tools`, newAllowed);
                    }}
                  />
                ))}
              </Accordion>
            </div>
          )}

          {/* OpenAPI Tools Section */}
          {openapiFields && openapiFields.length > 0 && (
            <div className="space-y-2">
              <h4 className="flex items-center gap-2 text-sm font-medium text-foreground">
                <Globe className="h-[14px] w-[14px] text-muted-foreground" />
                {t("create.openAPIConnections")}
              </h4>
              <div className="space-y-2">
                {openapiFields.map((item, index) => {
                  const connection = openapiConnections.find(
                    (c) => c.id === item.openapi_connection_id
                  );
                  const displayName =
                    (item as any).openapi_connection_name ||
                    connection?.name ||
                    item.openapi_connection_id;
                  const allowedTools: string[] = (item as any).allowed_tools || [];
                  const allTools = connection?.available_tools || [];
                  const activeCount =
                    allowedTools.length === 0
                      ? allTools.length
                      : allowedTools.length;

                  const currentLoadMode =
                    ((item as any).load_mode as
                      | "explicit"
                      | "searchable"
                      | undefined) ?? "explicit";

                  return (
                    <div
                      key={`openapi-${index}`}
                      className="flex items-center justify-between rounded-md border bg-card px-3 py-2"
                    >
                      <div className="flex items-center gap-2 min-w-0">
                        <Globe className="h-4 w-4 shrink-0 text-muted-foreground" />
                        <div className="min-w-0">
                          <p className="truncate text-sm font-medium">{displayName}</p>
                          {connection?.base_url && (
                            <p className="truncate text-xs text-muted-foreground">
                              {connection.base_url}
                            </p>
                          )}
                          <p className="text-xs text-muted-foreground">
                            {activeCount} of {allTools.length} operations
                          </p>
                        </div>
                      </div>
                      <div className="flex items-center gap-2 shrink-0">
                        <div
                          className="inline-flex items-center rounded-md border text-xs"
                          role="group"
                          aria-label="Load mode"
                        >
                          <button
                            type="button"
                            onClick={() =>
                              handleOpenapiLoadModeChange(
                                item.openapi_connection_id,
                                "explicit"
                              )
                            }
                            className={
                              "px-2 py-0.5 rounded-l-md " +
                              (currentLoadMode === "explicit"
                                ? "bg-accent text-accent-foreground"
                                : "text-muted-foreground hover:text-foreground")
                            }
                            aria-pressed={currentLoadMode === "explicit"}
                            title="Send every operation schema in every LLM call (legacy behavior, larger context)."
                          >
                            Explicit
                          </button>
                          <button
                            type="button"
                            onClick={() =>
                              handleOpenapiLoadModeChange(
                                item.openapi_connection_id,
                                "searchable"
                              )
                            }
                            className={
                              "px-2 py-0.5 rounded-r-md border-l " +
                              (currentLoadMode === "searchable"
                                ? "bg-accent text-accent-foreground"
                                : "text-muted-foreground hover:text-foreground")
                            }
                            aria-pressed={currentLoadMode === "searchable"}
                            title="Defer schemas behind a load_tools meta-tool; only a name+description catalog goes into the system prompt."
                          >
                            Searchable
                          </button>
                        </div>
                      <Button
                        type="button"
                        variant="ghost"
                        size="icon"
                        onClick={() => removeOpenapiTool?.(index)}
                        className="h-6 w-6 shrink-0 text-muted-foreground/60 hover:bg-transparent hover:text-red-500"
                        aria-label="Remove OpenAPI connection"
                      >
                        <svg
                          xmlns="http://www.w3.org/2000/svg"
                          viewBox="0 0 24 24"
                          fill="none"
                          stroke="currentColor"
                          strokeWidth="2"
                          strokeLinecap="round"
                          strokeLinejoin="round"
                          className="h-4 w-4"
                        >
                          <path d="M3 6h18" />
                          <path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6" />
                          <path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2" />
                        </svg>
                      </Button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Empty state - only show if no tools at all */}
          {(!builtinToolFields || builtinToolFields.length === 0) &&
            toolFields.length === 0 &&
            (!openapiFields || openapiFields.length === 0) && (
            <Note className="mt-2 cursor-default items-center gap-2 rounded-md border p-3 text-center text-xs text-muted-foreground/50">
              <p>{t("create.agentToolsDescription")}</p>  
              <p>{t("create.agentToolsNote")}</p>
            </Note>
          )}
        </div>
      </AccordionControl>

      {getNestedErrorMessage(errors, "tools_config.mcp_server_configs") && (
        <p className="form-error">
          {getNestedErrorMessage(errors, "tools_config.mcp_server_configs")}
        </p>
      )}
      {getNestedErrorMessage(errors, "tools_config.builtin_tools") && (
        <p className="form-error">
          {getNestedErrorMessage(errors, "tools_config.builtin_tools")}
        </p>
      )}
      {getNestedErrorMessage(errors, "tools_config") && (
        <p className="form-error">
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
              validateLoading={isChecking}
              forceCreateDisabled={
                isEditingInstance || isCreating || !instanceName.trim()
              }
              submitLabel={
                isCreating
                  ? isEditingInstance
                    ? tMcp("actions.updating")
                    : tMcp("actions.creating")
                  : isEditingInstance
                    ? tMcp("actions.updateInstance")
                    : tMcp("actions.createInstance")
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
