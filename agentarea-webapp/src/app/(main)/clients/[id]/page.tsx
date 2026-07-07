"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { Sparkles } from "lucide-react";
import { DetailSkeleton } from "@/components/Skeleton";
import ContentBlock from "@/components/ContentBlock";
import { SelectableList } from "@/components/SelectableList";
import { getMCPConnectionIconSrc } from "@/app/(main)/connections/utils";
import { useToast } from "@/hooks/use-toast";
import type {
  ClientResponse,
  SkillResponse,
  McpServerInstanceResponse,
  ProjectResponse,
} from "@/api/client";
import {
  getClientAction,
  addSkillToClientAction,
  removeSkillFromClientAction,
  addMcpInstanceToClientAction,
  removeMcpInstanceFromClientAction,
  pullClientFromProjectAction,
  listSkillsAction,
  listMCPServerInstancesAction,
  listProjectsAction,
} from "@/lib/server-actions";

export default function ClientDetailPage() {
  const params = useParams();
  const clientId = params.id as string;
  const { toast } = useToast();

  const [client, setClient] = useState<ClientResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [allSkills, setAllSkills] = useState<SkillResponse[]>([]);
  const [allMcp, setAllMcp] = useState<McpServerInstanceResponse[]>([]);
  const [allProjects, setAllProjects] = useState<ProjectResponse[]>([]);

  const fetchClient = async () => {
    const { data } = await getClientAction(clientId);
    if (data) setClient(data);
  };

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [clientRes, skillsRes, mcpRes, projectsRes] = await Promise.all([
          getClientAction(clientId),
          listSkillsAction(),
          listMCPServerInstancesAction(),
          listProjectsAction(),
        ]);
        if (clientRes.data) setClient(clientRes.data);
        setAllSkills((skillsRes.data as SkillResponse[]) || []);
        setAllMcp(mcpRes.data || []);
        setAllProjects(projectsRes.data || []);
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [clientId]);

  if (loading) return <DetailSkeleton />;
  if (!client) return null;

  const wrap = (fn: (id: string) => Promise<{ error?: unknown }>, ok: string, fail: string) =>
    async (id: string) => {
      const { error } = await fn(id);
      if (error) {
        toast({ title: "Error", description: fail, variant: "destructive" });
        return;
      }
      toast({ title: ok });
      await fetchClient();
    };

  const mcpAdd = wrap(
    (id) => addMcpInstanceToClientAction(clientId, id),
    "MCP instance added",
    "Failed to add MCP instance"
  );
  const mcpRemove = wrap(
    (id) => removeMcpInstanceFromClientAction(clientId, id),
    "MCP instance removed",
    "Failed to remove MCP instance"
  );
  const skillAdd = wrap(
    (id) => addSkillToClientAction(clientId, id),
    "Skill added",
    "Failed to add skill"
  );
  const skillRemove = wrap(
    (id) => removeSkillFromClientAction(clientId, id),
    "Skill removed",
    "Failed to remove skill"
  );

  const handlePull = async (projectId: string) => {
    const { error } = await pullClientFromProjectAction(clientId, projectId || null);
    if (error) {
      toast({ title: "Error", description: "Failed to set source project", variant: "destructive" });
      return;
    }
    toast({ title: projectId ? "Pulling bundle from project" : "Detached from project" });
    await fetchClient();
  };

  const syncCmd = `agentarea mcp sync --client=${clientId} --target=codex`;

  return (
    <ContentBlock header={{ breadcrumb: [{ label: "Clients", href: "/clients" }, { label: client.name }] }}>
      <div className="p-6 space-y-6">
        {client.description && (
          <p className="text-sm text-muted-foreground">{client.description}</p>
        )}

        <div className="rounded-lg border p-4 space-y-2">
          <h3 className="text-sm font-medium">Connect a harness</h3>
          <p className="text-xs text-muted-foreground">
            This client exposes a scoped MCP endpoint. Point any harness at it, or use the CLI:
          </p>
          <pre className="overflow-x-auto rounded bg-muted px-3 py-2 text-xs">{syncCmd}</pre>
          {client.mcp_endpoint_url && (
            <p className="text-xs text-muted-foreground break-all">
              Endpoint: <code>{client.mcp_endpoint_url}</code>
            </p>
          )}
        </div>

        <div className="space-y-2">
          <h3 className="text-sm font-medium">Pull bundle from project</h3>
          <select
            className="w-full max-w-sm rounded border bg-background px-3 py-2 text-sm"
            value={client.source_project_id || ""}
            onChange={(e) => handlePull(e.target.value)}
          >
            <option value="">None (standalone)</option>
            {allProjects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          {client.source_project_id && (
            <p className="text-xs text-muted-foreground">
              Effective bundle = this client&apos;s own attachments plus the source project&apos;s.
            </p>
          )}
        </div>

        <div className="grid gap-6 md:grid-cols-2">
          <div className="space-y-3">
            <h3 className="text-sm font-medium">
              MCP Instances ({(client.mcp_instances || []).length})
            </h3>
            {allMcp.length === 0 ? (
              <p className="text-sm text-muted-foreground">No MCP instances available.</p>
            ) : (
              <SelectableList
                items={allMcp}
                prefix="mcp"
                selectedIds={(client.mcp_instances || []).map((m) => m.id)}
                extractIconSrc={(mcp) => getMCPConnectionIconSrc(mcp) ?? "/Icon.svg"}
                extractTitle={(mcp) => (
                  <div className="flex min-w-0 flex-row items-center gap-1 px-[7px] py-[7px]">
                    <h3 className="truncate text-sm font-medium">{mcp.name}</h3>
                  </div>
                )}
                onAdd={(mcp) => mcpAdd(mcp.id)}
                onRemove={(mcp) => mcpRemove(mcp.id)}
                renderContent={(mcp) =>
                  mcp.description ? (
                    <p className="p-2 text-xs text-muted-foreground">{mcp.description}</p>
                  ) : null
                }
              />
            )}
          </div>

          <div className="space-y-3">
            <h3 className="text-sm font-medium">
              Skills ({(client.skills || []).length})
            </h3>
            {allSkills.length === 0 ? (
              <p className="text-sm text-muted-foreground">No skills available.</p>
            ) : (
              <SelectableList
                items={allSkills}
                prefix="skill"
                selectedIds={(client.skills || []).map((s) => s.id)}
                extractTitle={(skill) => (
                  <div className="flex min-w-0 flex-row items-center gap-1 px-[7px] py-[7px]">
                    <Sparkles className="h-4 w-4 shrink-0 text-muted-foreground" />
                    <h3 className="truncate text-sm font-medium">{skill.name}</h3>
                  </div>
                )}
                onAdd={(skill) => skillAdd(skill.id)}
                onRemove={(skill) => skillRemove(skill.id)}
                renderContent={(skill) =>
                  skill.description ? (
                    <p className="p-2 text-xs text-muted-foreground">{skill.description}</p>
                  ) : null
                }
              />
            )}
          </div>
        </div>
      </div>
    </ContentBlock>
  );
}
