import type { McpAppUiResource } from "@/lib/apps/mcp/tools";
import type { EntityIdentity } from "@/lib/entity-identity";
import type { OrgAgent, OrgTask, OrgTrigger } from "../utils/orgMap";

export type CanvasApp = {
  id: string;
  instanceId: string;
  toolName: string;
  title: string;
  connectionTitle: string;
  identity: EntityIdentity;
  resource: McpAppUiResource | null;
  error: string | null;
};

export type CanvasTask = OrgTask & {
  id: string;
  title: string;
  createdAt: string;
};

export type CanvasAgent = OrgAgent;
export type CanvasTrigger = OrgTrigger;

export type CanvasConnection = {
  id: string;
  title: string;
  identity: EntityIdentity;
  /** verification.status of the instance. */
  status: string;
};

export type CanvasData = {
  apps: CanvasApp[];
  tasks: CanvasTask[];
  agents: CanvasAgent[];
  triggers: CanvasTrigger[];
  connections: CanvasConnection[];
};
