"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowUpRight, FileText, Network } from "lucide-react";
import type {
  AgentResponse,
  McpServerInstanceResponse,
  McpServerResponse,
  ProjectResponse,
  SkillResponse,
} from "@/api/client";
import { getMCPConnectionIconSrc } from "@/app/(main)/connections/utils";
import {
  AttachmentSection,
  hydrateAttachments,
  type AttachmentItem,
} from "@/components/AttachmentSection";
import { DetailSkeleton } from "@/components/Skeleton";
import { Button } from "@/components/ui/button";
import Divider from "@/components/ui/divider";
import { ENTITY_ICONS, EntityIcon } from "@/lib/entity-icons";
import {
  addAgentToProjectAction,
  addMcpInstanceToProjectAction,
  addSkillToProjectAction,
  getProjectAction,
  listAgentsAction,
  listMCPServerInstancesAction,
  listMCPServersAction,
  listSkillsAction,
  removeAgentFromProjectAction,
  removeMcpInstanceFromProjectAction,
  removeSkillFromProjectAction,
} from "@/lib/server-actions";

const AgentIcon = ENTITY_ICONS.agent;
const McpIcon = ENTITY_ICONS.mcp;
const SkillIcon = ENTITY_ICONS.skill;

export default function ProjectOverviewPage() {
  const params = useParams();
  const projectId = params.id as string;

  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [allAgents, setAllAgents] = useState<AgentResponse[]>([]);
  const [allSkills, setAllSkills] = useState<SkillResponse[]>([]);
  const [allMcpInstances, setAllMcpInstances] = useState<
    McpServerInstanceResponse[]
  >([]);
  const [mcpServers, setMcpServers] = useState<McpServerResponse[]>([]);

  const fetchProject = useCallback(async () => {
    const { data } = await getProjectAction(projectId);
    if (data) setProject(data);
  }, [projectId]);

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [projectRes, agentsRes, skillsRes, mcpRes, serversRes] =
          await Promise.all([
            getProjectAction(projectId),
            listAgentsAction(),
            listSkillsAction(),
            listMCPServerInstancesAction(),
            listMCPServersAction({ page_size: 100 }),
          ]);
        if (projectRes.data) setProject(projectRes.data);
        setAllAgents(agentsRes.data || []);
        setAllSkills((skillsRes.data as SkillResponse[]) || []);
        setAllMcpInstances(mcpRes.data || []);
        const serversData = serversRes.data as
          | { items?: McpServerResponse[] }
          | McpServerResponse[]
          | undefined;
        setMcpServers(
          Array.isArray(serversData) ? serversData : serversData?.items || []
        );
      } finally {
        setLoading(false);
      }
    };
    load();
  }, [projectId]);

  if (loading) {
    return <DetailSkeleton />;
  }

  if (!project) return null;

  const instanceIconSrc = (instance: AttachmentItem) => {
    const full = allMcpInstances.find((i) => String(i.id) === instance.id);
    if (!full) return undefined;
    const spec = mcpServers.find((s) => s.id === full.server_spec_id);
    return getMCPConnectionIconSrc(full, spec);
  };

  const composition = [
    {
      kind: "agent" as const,
      label: "Agents",
      count: project.agents?.length || 0,
    },
    {
      kind: "skill" as const,
      label: "Skills",
      count: project.skills?.length || 0,
    },
    {
      kind: "mcp" as const,
      label: "MCP instances",
      count: project.mcp_instances?.length || 0,
    },
  ];

  return (
    <div className="mx-auto w-full max-w-[1180px] space-y-8 p-4 sm:p-6 lg:p-8">
      <section className="relative isolate overflow-hidden rounded-2xl border bg-card shadow-[0_18px_60px_-42px_rgba(15,23,42,0.55)]">
        <div
          aria-hidden="true"
          className="pointer-events-none absolute inset-0 -z-10 opacity-60 [background-image:radial-gradient(circle_at_1px_1px,hsl(var(--border))_1px,transparent_0)] [background-size:18px_18px] [mask-image:linear-gradient(to_right,black,transparent_72%)]"
        />
        <div className="grid lg:grid-cols-[minmax(0,1fr)_300px]">
          <div className="p-5 sm:p-7 lg:p-8">
            <div className="flex items-start gap-4">
              <span className="relative flex h-12 w-12 shrink-0 items-center justify-center overflow-hidden rounded-[14px] bg-primary text-primary-foreground shadow-sm">
                <EntityIcon kind="project" className="relative z-10 h-6 w-6" />
                <span className="bg-hatch-on-color pointer-events-none absolute inset-0" />
              </span>
              <div className="min-w-0">
                <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">
                  Project blueprint
                </p>
                <h1 className="mt-1 text-balance text-2xl font-semibold tracking-tight text-foreground">
                  {project.name}
                </h1>
                <p className="mt-2 max-w-2xl text-sm leading-6 text-muted-foreground">
                  {project.description ||
                    "A shared workspace for assembling agents, reusable skills, and connected tools."}
                </p>
              </div>
            </div>

            <div className="mt-7 rounded-xl border border-primary/10 bg-background/80 p-4 backdrop-blur-sm">
              <div className="flex items-center justify-between gap-3">
                <div className="flex items-center gap-2">
                  <FileText className="h-4 w-4 text-primary" />
                  <h2 className="text-sm font-semibold">
                    Operating instructions
                  </h2>
                </div>
                <Button
                  asChild
                  size="xs"
                  variant="ghost"
                  className="text-muted-foreground"
                >
                  <Link href={`/projects/${projectId}/settings`}>
                    Edit
                    <ArrowUpRight className="ml-1" />
                  </Link>
                </Button>
              </div>
              <p className="mt-2 whitespace-pre-wrap text-[13px] leading-5 text-muted-foreground">
                {project.instructions ||
                  "No operating instructions yet. Add guidance to keep every agent aligned."}
              </p>
            </div>
          </div>

          <aside className="border-t bg-muted/20 p-5 lg:border-l lg:border-t-0 lg:p-7">
            <div className="flex items-center gap-2">
              <Network className="h-4 w-4 text-primary" />
              <h2 className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                Network manifest
              </h2>
            </div>
            <div className="mt-5 divide-y rounded-xl border bg-background/90 px-4">
              {composition.map((item) => (
                <div key={item.kind} className="flex items-center gap-3 py-3.5">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <EntityIcon kind={item.kind} />
                  </span>
                  <span className="flex-1 text-sm font-medium">
                    {item.label}
                  </span>
                  <span className="font-mono text-sm font-semibold tabular-nums text-foreground">
                    {String(item.count).padStart(2, "0")}
                  </span>
                </div>
              ))}
            </div>
            <p className="mt-4 text-xs leading-5 text-muted-foreground">
              Resources connected here become the reusable building blocks for
              this project.
            </p>
          </aside>
        </div>
      </section>

      <section>
        <div className="flex flex-col gap-1 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="font-mono text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">
              Project topology
            </p>
            <h2 className="mt-1 text-lg font-semibold tracking-tight">
              Connected resources
            </h2>
          </div>
          <p className="max-w-md text-sm text-muted-foreground">
            Shape the network by attaching the capabilities this project can
            use.
          </p>
        </div>

        <div className="mt-5">
          <AttachmentSection
            id="project-agents"
            title="Agents"
            icon={AgentIcon}
            note={
              <p>Specialists that reason and act on behalf of the project.</p>
            }
            triggerText="Agent"
            sheetTitle="Agents"
            sheetDescription="Add agents to this project"
            availableTitle="Available Agents"
            attached={hydrateAttachments(project.agents, allAgents)}
            available={allAgents}
            emptyLabel="No agents connected yet."
            emptyAvailable={<p>No agents available. Create one first.</p>}
            onAdd={(item) => addAgentToProjectAction(projectId, item.id)}
            onRemove={(item) => removeAgentFromProjectAction(projectId, item.id)}
            onChanged={fetchProject}
          />

          <Divider />

          <AttachmentSection
            id="project-skills"
            title="Skills"
            icon={SkillIcon}
            note={<p>Reusable instructions that sharpen how agents work.</p>}
            triggerText="Skill"
            sheetTitle="Skills"
            sheetDescription="Add skills to this project"
            availableTitle="Available Skills"
            attached={hydrateAttachments(project.skills, allSkills)}
            available={allSkills}
            emptyLabel="No skills connected yet."
            emptyAvailable={<p>No skills available. Create one first.</p>}
            onAdd={(item) => addSkillToProjectAction(projectId, item.id)}
            onRemove={(item) => removeSkillFromProjectAction(projectId, item.id)}
            onChanged={fetchProject}
          />

          <Divider />

          <AttachmentSection
            id="project-mcp"
            title="MCP Servers"
            icon={McpIcon}
            note={
              <p>Live connections to tools, services, and external data.</p>
            }
            triggerText="MCP Server"
            sheetTitle="MCP Servers"
            sheetDescription="Add MCP server instances to this project"
            availableTitle="Active MCP Server Instances"
            attached={hydrateAttachments(project.mcp_instances, allMcpInstances)}
            available={allMcpInstances}
            emptyLabel="No MCP servers connected yet."
            emptyAvailable={
              <p>
                No MCP server instances yet. Create one under Connections first.
              </p>
            }
            onAdd={(item) => addMcpInstanceToProjectAction(projectId, item.id)}
            onRemove={(item) =>
              removeMcpInstanceFromProjectAction(projectId, item.id)
            }
            onChanged={fetchProject}
            getIconSrc={instanceIconSrc}
          />
        </div>
      </section>
    </div>
  );
}
