"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { DetailSkeleton } from "@/components/Skeleton";
import ContentBlock from "@/components/ContentBlock";
import { AssociationSection } from "../../projects/[id]/components/AssociationSection";
import { useToast } from "@/hooks/use-toast";
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

  const [client, setClient] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [allSkills, setAllSkills] = useState<any[]>([]);
  const [allMcp, setAllMcp] = useState<any[]>([]);
  const [allProjects, setAllProjects] = useState<any[]>([]);

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
        setAllSkills((skillsRes.data as any[]) || []);
        setAllMcp((mcpRes.data as any[]) || []);
        setAllProjects((projectsRes.data as any[]) || []);
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
        throw error;
      }
      toast({ title: ok });
      await fetchClient();
    };

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
          <AssociationSection
            title="MCP Instances"
            items={client.mcp_instances || []}
            allItems={allMcp}
            onAdd={wrap(
              (id) => addMcpInstanceToClientAction(clientId, id),
              "MCP instance added",
              "Failed to add MCP instance"
            )}
            onRemove={wrap(
              (id) => removeMcpInstanceFromClientAction(clientId, id),
              "MCP instance removed",
              "Failed to remove MCP instance"
            )}
            addLabel="Add MCP Instance"
            selectPlaceholder="Select an MCP instance..."
          />
          <AssociationSection
            title="Skills"
            items={client.skills || []}
            allItems={allSkills}
            onAdd={wrap(
              (id) => addSkillToClientAction(clientId, id),
              "Skill added",
              "Failed to add skill"
            )}
            onRemove={wrap(
              (id) => removeSkillFromClientAction(clientId, id),
              "Skill removed",
              "Failed to remove skill"
            )}
            addLabel="Add Skill"
            selectPlaceholder="Select a skill..."
          />
        </div>
      </div>
    </ContentBlock>
  );
}
