import React, { useCallback, useEffect, useMemo, useState } from "react";
import { useTranslations } from "next-intl";
import { Globe, Pencil, Wrench } from "lucide-react";
import {
  Control,
  FieldErrors,
  UseFieldArrayAppend,
  UseFieldArrayRemove,
  UseFieldArrayReturn,
  UseFormGetValues,
  UseFormSetValue,
  useWatch,
} from "react-hook-form";
import type { McpServerResponse, ToolResponse } from "@/api/client/types.gen";
import type { OpenAPIConnection } from "@/app/w/[workspace]/(main)/connections/types";
import AccordionControl from "@/components/AccordionControl";
import ConfigSheet from "@/components/ConfigSheet";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import { MCPInstanceConfigForm } from "@/components/MCPInstanceConfigForm";
import { PickerPanel } from "@/components/ResourcePicker/PickerPanel";
import { ResourcePickerList } from "@/components/ResourcePicker/ResourcePicker";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { SegmentedControl } from "@/components/ui/segmented-control";
import { Switch } from "@/components/ui/switch";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { deterministicHue } from "@/lib/avatar-hue";
import { getMCPConnectionIconSrc } from "@/lib/entity-identity";
import {
  McpAvailableTool,
  McpInstance,
  resolveMcpRef,
} from "@/lib/mcp/resolveMcpRef";
import {
  checkMCPServerInstanceConfigurationAction as checkMCPServerInstanceConfiguration,
  createMCPServerInstanceAction as createMCPServerInstance,
  getMCPServerInstanceAction as getMCPServerInstance,
  listOpenAPIConnectionsAction as listOpenAPIConnections,
  updateMCPServerInstanceAction as updateMCPServerInstance,
} from "@/lib/server-actions";
import type { AgentFormValues, MCPToolConfig } from "../types";
import { getBuiltinToolDisplayInfo } from "../utils/builtinToolUtils";
import { getNestedErrorMessage } from "../utils/formUtils";
import {
  CodeToolModelSettings,
  hasCodeToolModelSettings,
} from "./CodeToolModelSettings";
import {
  enabledMcpToolCount,
  McpToolSettings,
  type McpToolState,
} from "./McpToolSettings";
import { McpToolsTab } from "./McpToolsTab";
import { MethodsList } from "./MethodsList";
import type { Method } from "./MethodsList";
import { SelectedItemRow, SelectedItems } from "./SelectedItemRow";

type MCPServer = McpServerResponse;
type ToolGroup = NonNullable<ToolResponse["group"]>;

const TOOL_GROUP_MESSAGES: Record<
  ToolGroup,
  { label: string; description: string }
> = {
  sandbox: {
    label: "create.toolGroups.sandbox.label",
    description: "create.toolGroups.sandbox.description",
  },
};

/** How many of a tool's methods the agent gets, quiet at the row's edge. */
const countLabel = (picked: number, total: number) => (
  <span className="text-xs tabular-nums text-muted-foreground">
    {picked}/{total}
  </span>
);

interface BuiltinTool {
  name: string;
  display_name?: string;
  category?: string;
  description?: string;
  available_methods?: Method[];
  group?: ToolGroup | null;
}

type ToolConfigProps = {
  control: Control<AgentFormValues>;
  setValue: UseFormSetValue<AgentFormValues>;
  getValues: UseFormGetValues<AgentFormValues>;
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
  mcpInstanceList: McpInstance[];
  builtinTools: unknown[];
  builtinToolFields?: UseFieldArrayReturn<
    AgentFormValues,
    "tools_config.builtin_tools",
    "id"
  >["fields"];
  removeBuiltinTool?: UseFieldArrayRemove;
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
  getValues,
  errors,
  toolFields,
  removeTool,
  appendTool,
  mcpServers,
  mcpInstanceList,
  builtinTools: builtinToolsInput,
  builtinToolFields,
  removeBuiltinTool,
  appendBuiltinTool,
  openapiFields,
  removeOpenapiTool,
  appendOpenapiTool,
}: ToolConfigProps) => {
  const builtinTools = builtinToolsInput as BuiltinTool[];
  // Toolsets sharing a group are one switch; they never appear one by one
  const toolGroups = useMemo(() => {
    const groups = new Map<ToolGroup, BuiltinTool[]>();
    for (const tool of builtinTools) {
      if (tool.group) {
        groups.set(tool.group, [...(groups.get(tool.group) ?? []), tool]);
      }
    }
    return [...groups.entries()];
  }, [builtinTools]);
  const ungroupedBuiltinTools = builtinTools.filter((tool) => !tool.group);
  const groupedToolNames = new Set(
    builtinTools.filter((tool) => tool.group).map((tool) => tool.name)
  );
  const visibleBuiltinToolFields = (builtinToolFields ?? []).filter(
    (field) => !groupedToolNames.has(field.tool_name)
  );
  const [accordionValue, setAccordionValue] = useState<string>("tools");
  // A refused save opens the section, so the tool it points at is seen.
  const hasToolErrors = Boolean(errors.tools_config);
  useEffect(() => {
    if (hasToolErrors) setAccordionValue("tools");
  }, [hasToolErrors]);
  const [isSheetOpen, setIsSheetOpen] = useState(false);
  const [toolTab, setToolTab] = useState<"builtin" | "openapi" | "mcp">(
    "builtin"
  );
  const [toolQuery, setToolQuery] = useState("");
  // Methods unticked on a toolset not added yet; an added one keeps them in
  // its own disabled_methods.
  const [draftDisabledMethods, setDraftDisabledMethods] = useState<
    Record<string, Record<string, boolean>>
  >({});
  const t = useTranslations("AgentsPage");
  const watchedOpenapiConfigs = useWatch({
    control,
    name: "tools_config.openapi_configs",
  });
  const watchedBuiltinTools = useWatch({
    control,
    name: "tools_config.builtin_tools",
  });
  const watchedMcpConfigs = useWatch({
    control,
    name: "tools_config.mcp_server_configs",
  });
  // Picked tools whose settings are shown under their row.
  const [openTools, setOpenTools] = useState<string[]>([]);
  const toggleTool = (key: string) =>
    setOpenTools((keys) =>
      keys.includes(key) ? keys.filter((open) => open !== key) : [...keys, key]
    );
  const tMcp = useTranslations("MCPServersPage.createInstance");
  const tPickers = useTranslations("Pickers");
  const tCommon = useTranslations("Common");

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
  const [sheetError, setSheetError] = useState<string | null>(null);
  const [editError, setEditError] = useState<string | null>(null);

  // Keep a local copy of active instances so the list updates immediately after creation
  const [activeInstances, setActiveInstances] = useState<McpInstance[]>(
    mcpInstanceList || []
  );
  useEffect(() => {
    setActiveInstances(mcpInstanceList || []);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [JSON.stringify(mcpInstanceList)]);

  // OpenAPI connections state
  const [openapiConnections, setOpenapiConnections] = useState<
    OpenAPIConnection[]
  >([]);
  const [loadingOpenapiConnections, setLoadingOpenapiConnections] =
    useState(false);
  const [openapiLoadError, setOpenapiLoadError] = useState<string | null>(null);

  const loadOpenapiConnections = useCallback(() => {
    setLoadingOpenapiConnections(true);
    setOpenapiLoadError(null);
    listOpenAPIConnections()
      .then((result) => {
        if (result.error) {
          setOpenapiLoadError(
            apiErrorMessage(result, t("create.loadOpenapiConnectionsFailed"))
          );
          return;
        }
        const items = (result.data || []) as OpenAPIConnection[];
        setOpenapiConnections(Array.isArray(items) ? items : []);
      })
      .catch((err) => {
        console.error("Failed to load OpenAPI connections:", err);
        setOpenapiLoadError(
          `${t("create.loadOpenapiConnectionsFailed")}: ${formatApiError(err)}`
        );
      })
      .finally(() => {
        setLoadingOpenapiConnections(false);
      });
  }, [t]);

  useEffect(() => {
    loadOpenapiConnections();
  }, [loadOpenapiConnections]);

  // Which of a toolset's methods the agent gets: an added toolset reads its
  // saved disabled_methods, one still in the sheet its draft.
  const methodsSelection = (tool: BuiltinTool): Record<string, boolean> => {
    const added = watchedBuiltinTools?.find(
      (field) => field.tool_name === tool.name
    );
    const disabled = added
      ? (added.disabled_methods ?? {})
      : (draftDisabledMethods[tool.name] ?? {});
    return Object.fromEntries(
      (tool.available_methods ?? []).map((method) => [
        method.name,
        !(method.name in disabled),
      ])
    );
  };

  const handleAddBuiltinTool = (toolName: string) => {
    if (
      !appendBuiltinTool ||
      builtinToolFields?.some((field) => field.tool_name === toolName)
    )
      return;
    const disabled = draftDisabledMethods[toolName];
    appendBuiltinTool({
      tool_name: toolName,
      disabled_methods:
        disabled && Object.keys(disabled).length ? disabled : undefined,
    });
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

  const isToolGroupEnabled = (members: BuiltinTool[]) =>
    members.every((member) =>
      builtinToolFields?.some((field) => field.tool_name === member.name)
    );

  const setToolGroupEnabled = (members: BuiltinTool[], enabled: boolean) => {
    if (enabled) {
      const missing = members.filter(
        (member) =>
          !builtinToolFields?.some((field) => field.tool_name === member.name)
      );
      if (missing.length) {
        appendBuiltinTool?.(
          missing.map((member) => ({ tool_name: member.name }))
        );
      }
      return;
    }
    const indices = (builtinToolFields ?? []).flatMap((field, index) =>
      members.some((member) => member.name === field.tool_name) ? [index] : []
    );
    if (indices.length) removeBuiltinTool?.(indices);
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
    const operations = connection.available_tools ?? [];
    appendOpenapiTool({
      openapi_connection_id: connection.id,
      openapi_connection_name: connection.name,
      allowed_tools: operations.length
        ? operations.map((operation) => operation.name)
        : null,
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

    const connection = openapiConnections.find((c) => c.id === connectionId);
    const allToolNames = (connection?.available_tools || []).map((t) => t.name);

    // null means "all, including ones added later" — materialise on first toggle
    const current =
      getValues(`tools_config.openapi_configs.${index}.allowed_tools`) ??
      allToolNames;

    let updated: string[];
    if (enabled) {
      updated = current.includes(toolName) ? current : [...current, toolName];
    } else {
      updated = current.filter((t) => t !== toolName);
    }

    setValue(`tools_config.openapi_configs.${index}.allowed_tools`, updated);
  };

  const handleOpenapiAllTools = (index: number, all: boolean) => {
    const connectionId = getValues(
      `tools_config.openapi_configs.${index}.openapi_connection_id`
    );
    const connection = openapiConnections.find((c) => c.id === connectionId);
    setValue(
      `tools_config.openapi_configs.${index}.allowed_tools`,
      all ? null : (connection?.available_tools ?? []).map((t) => t.name)
    );
  };

  const handleMethodToggle = (
    toolName: string,
    methodName: string,
    checked: boolean
  ) => {
    const withToggle = (disabled: Record<string, boolean> = {}) => {
      const next = { ...disabled };
      if (checked) delete next[methodName];
      else next[methodName] = false;
      return next;
    };

    // Read through getValues, not the field array: its entries keep the
    // values they were appended with, so a second toggle would undo the first.
    const index = (getValues("tools_config.builtin_tools") ?? []).findIndex(
      (field) => field.tool_name === toolName
    );
    if (index === -1) {
      setDraftDisabledMethods((prev) => ({
        ...prev,
        [toolName]: withToggle(prev[toolName]),
      }));
      return;
    }
    const next = withToggle(
      getValues(`tools_config.builtin_tools.${index}.disabled_methods`) ??
        undefined
    );
    setValue(
      `tools_config.builtin_tools.${index}.disabled_methods`,
      Object.keys(next).length ? next : undefined,
      { shouldDirty: true }
    );
  };

  const getSelectedBuiltinTools = () =>
    builtinToolFields?.map((field) => ({
      tool_name: field.tool_name,
      disabled_methods: field.disabled_methods || {},
    })) || [];

  // Resolve a connection icon the same way the /connections page does: the icon
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

  // Known tools start as an explicit, fully ticked list; unknown ones start in
  // the visible "all tools" mode.
  const initialMcpAllowedTools = (
    tools: McpAvailableTool[]
  ): MCPToolConfig[] | null =>
    tools.length
      ? tools.map((tool) => ({
          tool_name: tool.name,
          requires_user_confirmation: false,
        }))
      : null;

  const createdInstanceTools = (created: McpInstance): McpAvailableTool[] => {
    const res = resolveMcpRef(created.id, [created], mcpServers);
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

  // A toolset's methods, ticked in place under its row in the sheet.
  const renderBuiltinMethods = (tool: BuiltinTool, wide = false) =>
    tool.available_methods?.length ? (
      <MethodsList
        wide={wide}
        methods={tool.available_methods}
        selectedMethods={methodsSelection(tool)}
        onMethodToggle={(methodName, checked) =>
          handleMethodToggle(tool.name, methodName, checked)
        }
        toolName={tool.name}
        showSelectAll
        onSelectAll={(checked) =>
          tool.available_methods?.forEach((method: Method) =>
            handleMethodToggle(tool.name, method.name, checked)
          )
        }
      />
    ) : null;

  // An OpenAPI connection's operations, picked one by one; with "all tools"
  // on, every one is ticked.
  const renderOpenapiOperations = (connectionId: string, wide = false) => {
    const index = (openapiFields ?? []).findIndex(
      (field) => field.openapi_connection_id === connectionId
    );
    const connection = openapiConnections.find((c) => c.id === connectionId);
    const operations = connection?.available_tools ?? [];
    if (index === -1 || !operations.length) return null;
    const allowed = watchedOpenapiConfigs?.[index]?.allowed_tools ?? null;
    return (
      <MethodsList
        wide={wide}
        label={t("create.openapiOperationsLabel")}
        methods={operations}
        selectedMethods={Object.fromEntries(
          operations.map((operation) => [
            operation.name,
            allowed === null || allowed.includes(operation.name),
          ])
        )}
        onMethodToggle={(name, checked) =>
          handleOpenapiToolToggle(connectionId, name, checked)
        }
        toolName={`openapi-${connectionId}`}
        showSelectAll
        onSelectAll={(checked) =>
          setValue(
            `tools_config.openapi_configs.${index}.allowed_tools`,
            checked ? operations.map((operation) => operation.name) : []
          )
        }
      />
    );
  };

  const handleMcpToolState = (
    index: number,
    tools: McpAvailableTool[],
    toolName: string,
    state: McpToolState
  ) => {
    // null means "all, including ones added later" — materialise on first toggle
    const current: MCPToolConfig[] =
      getValues(`tools_config.mcp_server_configs.${index}.allowed_tools`) ??
      tools.map((tool) => ({ tool_name: tool.name }));
    const requiresApproval = state === "approval_required";
    const next =
      state === "disabled"
        ? current.filter((config) => config.tool_name !== toolName)
        : current.some((config) => config.tool_name === toolName)
          ? current.map((config) =>
              config.tool_name === toolName
                ? { ...config, requires_user_confirmation: requiresApproval }
                : config
            )
          : [
              ...current,
              {
                tool_name: toolName,
                requires_user_confirmation: requiresApproval,
              },
            ];
    setValue(`tools_config.mcp_server_configs.${index}.allowed_tools`, next);
  };

  const handleAddTools = (servers: McpInstance[]) => {
    if (!servers?.length) return;

    const configs = servers.map((server) => ({
      mcp_server_id: server.id,
      allowed_tools: initialMcpAllowedTools(getInstanceTools(server)),
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
    (server.env_schema || []).forEach((envVar) => {
      const name = (envVar && (envVar.name as string)) || "";
      if (!name) return;
      const defVal = (envVar.default as string | undefined) || "";
      initialEnv[name] = defVal;
    });
    setEnvVars(initialEnv);
    setValidationResult(null);
    setSheetError(null);
    setConfigureServerSheetOpen(true);
  };

  const editTool = async (index: number) => {
    const tool = toolFields[index];
    if (!tool) return;
    setEditError(null);
    try {
      const instanceId = tool.mcp_server_id;
      const result = await getMCPServerInstance(instanceId);
      const instance = result.data;
      if (result.error || !instance) {
        setEditError(apiErrorMessage(result, t("create.loadInstanceFailed")));
        return;
      }
      const serverSpec =
        mcpServers.find((s) => s.id === instance.server_spec_id) || null;
      if (!serverSpec) {
        setEditError(tMcp("errors.specNotFound"));
        return;
      }
      setSelectedServer(serverSpec);
      setIsEditingInstance(true);
      setEditingInstanceId(instanceId);
      setInstanceName(instance.name || "");
      setInstanceDescription(instance.description || "");
      const env =
        (instance.json_spec?.environment as Record<string, string>) || {};
      setEnvVars(env);
      setValidationResult(null);
      setSheetError(null);
      setConfigureServerSheetOpen(true);
    } catch (e) {
      console.error("Failed to open MCP instance edit form", e);
      setEditError(`${t("create.loadInstanceFailed")}: ${formatApiError(e)}`);
    }
  };

  const note = useMemo(() => <p>{t("create.agentToolsLead")}</p>, [t]);

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
        count={
          visibleBuiltinToolFields.length +
          toolFields.length +
          (openapiFields?.length ?? 0) +
          toolGroups.filter(([, members]) => isToolGroupEnabled(members)).length
        }
        accordionValue={accordionValue}
        setAccordionValue={setAccordionValue}
        title={title}
        noteInline
        note={note}
        mainControl={
          <ConfigSheet
            title={t("create.toolsMcp")}
            description={t("create.toolsMcpDescription")}
            triggerText={t("create.tool")}
            className="ml-auto"
            triggerVariant="primaryOutline"
            open={isSheetOpen}
            onOpenChange={setIsSheetOpen}
            panel
          >
            <PickerPanel
              title={t("create.toolsMcp")}
              description={t("create.toolsMcpDescription")}
              onSearch={setToolQuery}
              tabs={
                <CountSegmentedControl
                  layoutId="tools-tabs"
                  value={toolTab}
                  onChange={setToolTab}
                  items={[
                    {
                      value: "builtin",
                      label: t("create.toolsTabBuiltin"),
                      count: visibleBuiltinToolFields.length || undefined,
                    },
                    {
                      value: "openapi",
                      label: "OpenAPI",
                      count: openapiFields?.length || undefined,
                    },
                    {
                      value: "mcp",
                      label: "MCP",
                      count: toolFields.length || undefined,
                    },
                  ]}
                />
              }
              manageText={
                toolTab === "mcp"
                  ? tPickers("manageMcpsLink")
                  : t("create.manageConnections")
              }
              manageHref={toolTab === "builtin" ? undefined : "/connections"}
            >
              {toolTab === "builtin" && (
                <ResourcePickerList
                  query={toolQuery}
                  heading={t("create.builtinTools")}
                  items={ungroupedBuiltinTools.map((tool) => ({
                    ...tool,
                    id: tool.name,
                  }))}
                  selectedIds={getSelectedBuiltinTools().map(
                    (tool) => tool.tool_name
                  )}
                  onAdd={(tool) => handleAddBuiltinTool(tool.name)}
                  onRemove={(tool) => handleRemoveBuiltinTool(tool.name)}
                  extractTitle={(tool) =>
                    getBuiltinToolDisplayInfo(tool).displayName
                  }
                  extractSubtitle={(tool) =>
                    getBuiltinToolDisplayInfo(tool).description
                  }
                  extractIcon={(tool) => {
                    const { IconComponent } = getBuiltinToolDisplayInfo(tool);
                    return <IconComponent strokeWidth={1.85} />;
                  }}
                  loading={false}
                  failed={false}
                  onRefresh={() => undefined}
                  emptyTitle={t("create.noBuiltinTools")}
                  renderExpanded={renderBuiltinMethods}
                />
              )}
              {toolTab === "openapi" && (
                <ResourcePickerList
                  query={toolQuery}
                  heading={t("create.openAPIConnections")}
                  items={openapiConnections}
                  selectedIds={(openapiFields || []).map(
                    (field) => field.openapi_connection_id
                  )}
                  onAdd={(connection) => handleAddOpenapiConnection(connection)}
                  onRemove={(connection) =>
                    handleRemoveOpenapiConnection(connection.id)
                  }
                  extractTitle={(connection) => connection.name}
                  extractSubtitle={(connection) =>
                    [
                      connection.base_url,
                      t("create.openapiOperations", {
                        count: connection.available_tools?.length ?? 0,
                      }),
                    ]
                      .filter(Boolean)
                      .join(" · ")
                  }
                  extractIcon={() => <Globe strokeWidth={1.85} />}
                  loading={loadingOpenapiConnections}
                  failed={Boolean(openapiLoadError)}
                  onRefresh={loadOpenapiConnections}
                  emptyTitle={t("create.noOpenapiConnections")}
                  emptyHint={t("create.noOpenapiConnectionsHint")}
                  createText={t("create.connectOpenapi")}
                  createHref="/connections"
                  renderExpanded={(connection) =>
                    renderOpenapiOperations(connection.id)
                  }
                />
              )}
              {toolTab === "mcp" && (
                <McpToolsTab
                  query={toolQuery}
                  instances={activeInstances}
                  servers={mcpServers}
                  selectedIds={toolFields.map((item) => item.mcp_server_id)}
                  onAdd={(instance) => handleAddTools([instance])}
                  onRemove={(instance) => handleRemoveTool(instance.id)}
                  onConfigure={handleAddConfigurationTools}
                  instanceIconSrc={instanceIconSrc}
                  instanceSubtitle={(instance) => {
                    const res = resolveMcpRef(
                      instance.id,
                      activeInstances,
                      mcpServers
                    );
                    return res.status === "instance"
                      ? (res.server?.name ?? null)
                      : null;
                  }}
                  serverIconSrc={serverIconSrc}
                />
              )}
            </PickerPanel>
          </ConfigSheet>
        }
      >
        <div className="space-y-2">
          {toolGroups.length > 0 && (
            <div className="overflow-hidden rounded-md border">
              {toolGroups.map(([group, members]) => (
                <SelectedItemRow
                  key={group}
                  avatar={
                    <EntityAvatar
                      hue={deterministicHue(group)}
                      size={24}
                      iconScale={0.45}
                      icon={<Wrench strokeWidth={1.85} />}
                      aria-hidden
                    />
                  }
                  title={
                    <label
                      htmlFor={`tool-group-${group}`}
                      className="cursor-pointer"
                    >
                      {t(TOOL_GROUP_MESSAGES[group].label)}
                    </label>
                  }
                  subtitle={t(TOOL_GROUP_MESSAGES[group].description)}
                  end={
                    <Switch
                      id={`tool-group-${group}`}
                      checked={isToolGroupEnabled(members)}
                      onCheckedChange={(enabled) =>
                        setToolGroupEnabled(members, enabled)
                      }
                    />
                  }
                />
              ))}
            </div>
          )}

          <SelectedItems
            count={
              visibleBuiltinToolFields.length +
              toolFields.length +
              (openapiFields?.length ?? 0)
            }
            empty={t("create.agentToolsDescription")}
          >
            {(builtinToolFields ?? []).map((item, index) => {
              const builtinTool = builtinTools.find(
                (tool) => tool.name === item.tool_name
              );
              if (!builtinTool || builtinTool.group) return null;
              const { IconComponent, displayName, description } =
                getBuiltinToolDisplayInfo(builtinTool);
              const methods = builtinTool.available_methods ?? [];
              const selection = methodsSelection(builtinTool);
              const picked = methods.filter(
                (method) => selection[method.name]
              ).length;
              const key = `builtin-${builtinTool.name}`;
              const hasSettings =
                methods.length > 0 ||
                hasCodeToolModelSettings(builtinTool.name);
              return (
                <SelectedItemRow
                  key={key}
                  open={openTools.includes(key)}
                  onOpenChange={hasSettings ? () => toggleTool(key) : undefined}
                  avatar={
                    <EntityAvatar
                      hue={deterministicHue(builtinTool.name)}
                      size={24}
                      iconScale={0.45}
                      icon={<IconComponent strokeWidth={1.85} />}
                      aria-hidden
                    />
                  }
                  title={displayName}
                  subtitle={description}
                  end={methods.length > 0 && countLabel(picked, methods.length)}
                  removeLabel={t("create.removeTool", { name: displayName })}
                  onRemove={() => removeBuiltinTool?.(index)}
                >
                  {hasSettings && (
                    <>
                      <CodeToolModelSettings
                        toolName={builtinTool.name}
                        index={index}
                        control={control}
                        setValue={setValue}
                      />
                      {renderBuiltinMethods(builtinTool, true)}
                    </>
                  )}
                </SelectedItemRow>
              );
            })}

            {toolFields.map((item, index) => {
              const trigger = resolveInstanceTrigger(item.mcp_server_id);
              const allowed = watchedMcpConfigs?.[index]?.allowed_tools ?? null;
              const tools = trigger.available_tools;
              const key = `mcp-${item.mcp_server_id}`;
              return (
                <SelectedItemRow
                  key={key}
                  open={openTools.includes(key)}
                  onOpenChange={() => toggleTool(key)}
                  avatar={
                    <EntityAvatar
                      // A server's own logo sits on a neutral plate; a glyph takes a hue.
                      {...(trigger.iconSrc
                        ? { variant: "soft" as const }
                        : { hue: deterministicHue(item.mcp_server_id) })}
                      size={24}
                      iconScale={trigger.iconSrc ? 0.68 : 0.45}
                      src={trigger.iconSrc}
                      icon={<Wrench strokeWidth={1.85} />}
                      aria-hidden
                    />
                  }
                  title={trigger.name}
                  badge={
                    <Badge variant="outline" className="shrink-0 self-center">
                      MCP
                    </Badge>
                  }
                  subtitle={trigger.description}
                  end={
                    tools.length > 0 &&
                    countLabel(
                      enabledMcpToolCount(tools, allowed),
                      tools.length
                    )
                  }
                  actionCount={1}
                  actions={
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      onClick={() => editTool(index)}
                      className="h-7 w-7 text-muted-foreground hover:text-foreground"
                      aria-label={t("create.editTool", { name: trigger.name })}
                    >
                      <Pencil className="h-3.5 w-3.5" />
                    </Button>
                  }
                  removeLabel={t("create.removeTool", { name: trigger.name })}
                  onRemove={() => removeTool(index)}
                >
                  <McpToolSettings
                    id={key}
                    tools={tools}
                    allowed={allowed}
                    onAllToolsChange={(all) =>
                      setValue(
                        `tools_config.mcp_server_configs.${index}.allowed_tools`,
                        all ? null : (initialMcpAllowedTools(tools) ?? [])
                      )
                    }
                    onToolStateChange={(toolName, state) =>
                      handleMcpToolState(index, tools, toolName, state)
                    }
                  />
                </SelectedItemRow>
              );
            })}

            {(openapiFields ?? []).map((item, index) => {
              const connection = openapiConnections.find(
                (c) => c.id === item.openapi_connection_id
              );
              const displayName =
                item.openapi_connection_name ||
                connection?.name ||
                item.openapi_connection_id;
              const allowedTools =
                watchedOpenapiConfigs?.[index]?.allowed_tools ?? null;
              const allTools = connection?.available_tools || [];
              const activeCount =
                allowedTools === null ? allTools.length : allowedTools.length;
              const loadMode =
                watchedOpenapiConfigs?.[index]?.load_mode ?? "explicit";
              const key = `openapi-${item.openapi_connection_id}`;
              return (
                <SelectedItemRow
                  key={key}
                  open={openTools.includes(key)}
                  onOpenChange={() => toggleTool(key)}
                  avatar={
                    <EntityAvatar
                      hue={deterministicHue(item.openapi_connection_id)}
                      size={24}
                      iconScale={0.45}
                      icon={<Globe strokeWidth={1.85} />}
                      aria-hidden
                    />
                  }
                  title={displayName}
                  badge={
                    <Badge variant="outline" className="shrink-0 self-center">
                      OpenAPI
                    </Badge>
                  }
                  subtitle={connection?.base_url}
                  end={
                    allTools.length > 0 &&
                    countLabel(activeCount, allTools.length)
                  }
                  removeLabel={t("create.removeTool", { name: displayName })}
                  onRemove={() => removeOpenapiTool?.(index)}
                >
                  <div className="space-y-2">
                    <p className="text-xs font-medium text-foreground">
                      {t("create.loadMode.label")}
                    </p>
                    <SegmentedControl
                      layoutId={`${key}-load-mode`}
                      value={loadMode}
                      onChange={(mode) =>
                        handleOpenapiLoadModeChange(
                          item.openapi_connection_id,
                          mode
                        )
                      }
                      items={(["explicit", "searchable"] as const).map(
                        (mode) => ({
                          value: mode,
                          label: t(`create.loadMode.${mode}`),
                        })
                      )}
                    />
                    <p className="note">
                      {t(`create.loadMode.${loadMode}Hint`)}
                    </p>
                  </div>
                  <div className="flex items-center gap-2">
                    <Switch
                      id={`${key}-all-tools`}
                      size="xs"
                      checked={allowedTools === null}
                      onCheckedChange={(all) =>
                        handleOpenapiAllTools(index, all)
                      }
                    />
                    <label
                      htmlFor={`${key}-all-tools`}
                      className="cursor-pointer text-xs text-foreground"
                    >
                      {t("create.allToolsIncludingNew")}
                    </label>
                  </div>
                  {renderOpenapiOperations(item.openapi_connection_id, true)}
                </SelectedItemRow>
              );
            })}
          </SelectedItems>
        </div>
      </AccordionControl>

      {editError && <FormError className="mt-2">{editError}</FormError>}
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
            ? t(
                isEditingInstance
                  ? "create.editInstanceTitle"
                  : "create.configureInstanceTitle",
                { name: selectedServer.name }
              )
            : t("create.configureMcpServer")
        }
        description={selectedServer?.description || ""}
        triggerClassName="hidden"
        open={configureServerSheetOpen}
        onOpenChange={setConfigureServerSheetOpen}
      >
        {selectedServer && (
          <div className="flex flex-col gap-4 overflow-y-auto pb-4">
            {sheetError && <FormError>{sheetError}</FormError>}
            {validationResult &&
              (validationResult.valid ? (
                <p className="text-xs text-muted-foreground">
                  {tMcp("success.valid")}
                </p>
              ) : (
                <FormError>
                  {tMcp("warnings.hasErrors", {
                    count: validationResult.errors?.length || 0,
                  })}
                  {validationResult.errors?.length
                    ? `: ${validationResult.errors.join(", ")}`
                    : ""}
                </FormError>
              ))}
            <MCPInstanceConfigForm
              renderAsForm={false}
              server={selectedServer}
              instanceName={instanceName}
              instanceDescription={instanceDescription}
              envVars={envVars}
              onChangeName={(value) => {
                setInstanceName(value);
                setSheetError(null);
              }}
              onChangeDescription={(value) => {
                setInstanceDescription(value);
                setSheetError(null);
              }}
              onChangeEnvVar={(name, value) => {
                setEnvVars((prev) => ({ ...prev, [name]: value }));
                setSheetError(null);
                if (validationResult) setValidationResult(null);
              }}
              onValidate={async () => {
                if (!selectedServer) return;
                setIsChecking(true);
                setSheetError(null);
                try {
                  const check = await checkMCPServerInstanceConfiguration({
                    json_spec: {
                      image: selectedServer.docker_image_url,
                      port: 8000,
                      environment: envVars,
                    },
                  });
                  if (check.error) {
                    setSheetError(
                      apiErrorMessage(check, tMcp("errors.validateFailed"))
                    );
                  } else {
                    setValidationResult(
                      check.data as {
                        valid: boolean;
                        errors: string[];
                        warnings: string[];
                      } | null
                    );
                  }
                } catch (err) {
                  console.error("MCP instance validation failed", err);
                  setSheetError(
                    `${tMcp("errors.validateFailed")}: ${formatApiError(err)}`
                  );
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
                      setSheetError(null);
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
                        if (res.error) {
                          setSheetError(
                            apiErrorMessage(res, tMcp("errors.createFailed"))
                          );
                          return;
                        }
                        if (res.data?.id) {
                          const created = res.data;
                          setActiveInstances((prev) => {
                            const exists = prev.some(
                              (i) => i.id === created.id
                            );
                            return exists ? prev : [created, ...prev];
                          });
                          appendTool([
                            {
                              mcp_server_id: created.id,
                              allowed_tools: initialMcpAllowedTools(
                                createdInstanceTools(created)
                              ),
                            },
                          ]);
                        }
                        setConfigureServerSheetOpen(false);
                      } catch (err) {
                        console.error("MCP instance creation failed", err);
                        setSheetError(
                          `${tMcp("errors.createFailed")}: ${formatApiError(err)}`
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
                    setSheetError(tMcp("warnings.validateFirst"));
                    return;
                  }
                  if (validationResult && !validationResult.valid) {
                    setSheetError(tMcp("errors.validationFailedForceCreate"));
                    return;
                  }
                }
                setIsCreating(true);
                setSheetError(null);
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
                    };
                    const updated = await updateMCPServerInstance(
                      editingInstanceId,
                      payload
                    );
                    if (updated.error) {
                      setSheetError(
                        apiErrorMessage(
                          updated,
                          t("create.updateInstanceFailed")
                        )
                      );
                      return;
                    }
                    setActiveInstances((prev) =>
                      prev.map((i) =>
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
                    if (res.error) {
                      setSheetError(
                        apiErrorMessage(res, tMcp("errors.createFailed"))
                      );
                      return;
                    }
                    if (res.data?.id) {
                      const created = res.data;
                      setActiveInstances((prev) => {
                        const exists = prev.some((i) => i.id === created.id);
                        return exists ? prev : [created, ...prev];
                      });
                      appendTool([
                        {
                          mcp_server_id: created.id,
                          allowed_tools: initialMcpAllowedTools(
                            createdInstanceTools(created)
                          ),
                        },
                      ]);
                    }
                  }
                  setConfigureServerSheetOpen(false);
                  setIsEditingInstance(false);
                  setEditingInstanceId(null);
                } catch (err) {
                  console.error("MCP instance save failed", err);
                  setSheetError(
                    `${
                      isEditingInstance
                        ? t("create.updateInstanceFailed")
                        : tMcp("errors.createFailed")
                    }: ${formatApiError(err)}`
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
                  {tCommon("cancel")}
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
