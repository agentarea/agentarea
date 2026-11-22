import type { Metadata } from "next";
import type { McpServerInstanceResponse } from "@/api/client/types.gen";
import {
  getAllTasks,
  getMCPServer,
  listAgents,
  listMCPServerInstances,
  listTriggers,
} from "@/lib/api";
import { readMcpAppUiResource } from "@/lib/apps/mcp/proxy-client";
import { mcpAppEntries } from "@/lib/apps/mcp/tools";
import { mcpIdentity } from "@/lib/entity-identity";
import { optionalApiData, requireApiData } from "@/lib/server-resource";
import { getTaskSource } from "@/lib/taskSource";
import { getMCPConnectionTitle } from "../connections/utils";
import type {
  CanvasAgent,
  CanvasApp,
  CanvasConnection,
  CanvasTask,
  CanvasTrigger,
} from "./components/canvasTypes";
import CanvasWorkspace from "./components/CanvasWorkspace";
import { taskSource, triggerSource } from "./utils/orgMap";

export const metadata: Metadata = {
  title: "Canvas",
};

const CANVAS_TASKS = 100;

async function loadConnections(): Promise<{
  apps: CanvasApp[];
  connections: CanvasConnection[];
}> {
  const instances: McpServerInstanceResponse[] = requireApiData(
    await listMCPServerInstances(),
    "MCP connections"
  );
  const specIds = [
    ...new Set(instances.flatMap((instance) => instance.server_spec_id ?? [])),
  ];
  const specs = new Map(
    await Promise.all(
      specIds.map(
        async (id) =>
          [
            id,
            optionalApiData(await getMCPServer(id), `MCP server ${id}`),
          ] as const
      )
    )
  );
  const specOf = (instance: McpServerInstanceResponse) =>
    instance.server_spec_id ? specs.get(instance.server_spec_id) : null;
  const instanceById = new Map(instances.map((i) => [i.id, i]));

  const connections = instances.map((instance) => ({
    id: instance.id,
    title: getMCPConnectionTitle(instance, specOf(instance)),
    identity: mcpIdentity(instance, specOf(instance)),
    status:
      typeof instance.verification?.status === "string"
        ? instance.verification.status
        : "never_attempted",
  }));

  const entries = mcpAppEntries(instances).filter((app) => !app.requiresInput);
  const apps = await Promise.all(
    entries.map(async (app) => {
      const instance = instanceById.get(app.instanceId);
      const spec = instance ? specOf(instance) : null;
      const loaded = await readMcpAppUiResource(
        app.instanceId,
        app.resourceUri
      ).then(
        (resource) => ({ resource, error: null }),
        (error: unknown) => ({
          resource: null,
          error: error instanceof Error ? error.message : String(error),
        })
      );
      return {
        id: `app:${app.instanceId}:${app.toolName}`,
        instanceId: app.instanceId,
        toolName: app.toolName,
        title: app.title || app.toolName,
        connectionTitle: instance
          ? getMCPConnectionTitle(instance, spec)
          : app.instanceName,
        identity: mcpIdentity(instance ?? {}, spec),
        ...loaded,
      };
    })
  );
  return { apps, connections };
}

async function loadTasks(): Promise<CanvasTask[]> {
  const { data, error } = await getAllTasks({ limit: CANVAS_TASKS, offset: 0 });
  if (error || !data) {
    console.error("Canvas: failed to load tasks", error);
    return [];
  }
  return data.map((task) => ({
    id: task.id,
    agentId: task.agent_id,
    title: task.description,
    status: task.status,
    agentName: task.agent_name ?? null,
    createdAt: task.created_at,
    totalCost: task.total_cost ?? null,
    source: taskSource(getTaskSource(task.parameters ?? {}).kind),
  }));
}

async function loadAgents(): Promise<CanvasAgent[]> {
  const { data, error } = await listAgents();
  if (error || !data) {
    console.error("Canvas: failed to load agents", error);
    return [];
  }
  return data.map((agent) => ({
    id: agent.id,
    name: agent.name,
    connectionIds: (agent.tools ?? []).flatMap((tool) =>
      tool.type === "mcp" ? [tool.name] : []
    ),
  }));
}

async function loadTriggers(): Promise<CanvasTrigger[]> {
  const { data, error } = await listTriggers();
  if (error || !data) {
    console.error("Canvas: failed to load triggers", error);
    return [];
  }
  return data.map((trigger) => ({
    id: trigger.id,
    name: trigger.name,
    source: triggerSource(trigger.trigger_type),
    agentId: trigger.agent_id,
    active: trigger.is_active,
    streamId: trigger.stream_id ?? null,
  }));
}

export default async function CanvasPage() {
  const [{ apps, connections }, tasks, agents, triggers] = await Promise.all([
    loadConnections(),
    loadTasks(),
    loadAgents(),
    loadTriggers(),
  ]);
  return (
    <CanvasWorkspace data={{ apps, tasks, agents, triggers, connections }} />
  );
}
