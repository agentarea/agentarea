"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { ArrowUpRight, FileText, Network } from "lucide-react";
import type {
  AgentResponse,
  McpServerInstanceResponse,
  ProjectResponse,
  SkillResponse,
} from "@/api/client";
import { DetailSkeleton } from "@/components/Skeleton";
import { Button } from "@/components/ui/button";
import { useToast } from "@/hooks/use-toast";
import { EntityIcon } from "@/lib/entity-icons";
import {
  addAgentToProjectAction,
  addMcpInstanceToProjectAction,
  addSkillToProjectAction,
  getProjectAction,
  listAgentsAction,
  listMCPServerInstancesAction,
  listSkillsAction,
  removeAgentFromProjectAction,
  removeMcpInstanceFromProjectAction,
  removeSkillFromProjectAction,
} from "@/lib/server-actions";
import { AssociationSection } from "./components/AssociationSection";

export default function ProjectOverviewPage() {
  const params = useParams();
  const projectId = params.id as string;
  const { toast } = useToast();

  const [project, setProject] = useState<ProjectResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [allAgents, setAllAgents] = useState<AgentResponse[]>([]);
  const [allSkills, setAllSkills] = useState<SkillResponse[]>([]);
  const [allMcpInstances, setAllMcpInstances] = useState<
    McpServerInstanceResponse[]
  >([]);

  const fetchProject = async () => {
    const { data } = await getProjectAction(projectId);
    if (data) setProject(data);
  };

  useEffect(() => {
    const load = async () => {
      setLoading(true);
      try {
        const [projectRes, agentsRes, skillsRes, mcpRes] = await Promise.all([
          getProjectAction(projectId),
          listAgentsAction(),
          listSkillsAction(),
          listMCPServerInstancesAction(),
        ]);
        if (projectRes.data) setProject(projectRes.data);
        setAllAgents(agentsRes.data || []);
        setAllSkills((skillsRes.data as SkillResponse[]) || []);
        setAllMcpInstances(mcpRes.data || []);
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

  const handleAddAgent = async (agentId: string) => {
    const { error } = await addAgentToProjectAction(projectId, agentId);
    if (error) {
      toast({
        title: "Error",
        description: "Failed to add agent",
        variant: "destructive",
      });
      throw error;
    }
    toast({ title: "Agent added" });
    await fetchProject();
  };

  const handleRemoveAgent = async (agentId: string) => {
    const { error } = await removeAgentFromProjectAction(projectId, agentId);
    if (error) {
      toast({
        title: "Error",
        description: "Failed to remove agent",
        variant: "destructive",
      });
      throw error;
    }
    toast({ title: "Agent removed" });
    await fetchProject();
  };

  const handleAddSkill = async (skillId: string) => {
    const { error } = await addSkillToProjectAction(projectId, skillId);
    if (error) {
      toast({
        title: "Error",
        description: "Failed to add skill",
        variant: "destructive",
      });
      throw error;
    }
    toast({ title: "Skill added" });
    await fetchProject();
  };

  const handleRemoveSkill = async (skillId: string) => {
    const { error } = await removeSkillFromProjectAction(projectId, skillId);
    if (error) {
      toast({
        title: "Error",
        description: "Failed to remove skill",
        variant: "destructive",
      });
      throw error;
    }
    toast({ title: "Skill removed" });
    await fetchProject();
  };

  const handleAddMcp = async (mcpId: string) => {
    const { error } = await addMcpInstanceToProjectAction(projectId, mcpId);
    if (error) {
      toast({
        title: "Error",
        description: "Failed to add MCP instance",
        variant: "destructive",
      });
      throw error;
    }
    toast({ title: "MCP instance added" });
    await fetchProject();
  };

  const handleRemoveMcp = async (mcpId: string) => {
    const { error } = await removeMcpInstanceFromProjectAction(
      projectId,
      mcpId
    );
    if (error) {
      toast({
        title: "Error",
        description: "Failed to remove MCP instance",
        variant: "destructive",
      });
      throw error;
    }
    toast({ title: "MCP instance removed" });
    await fetchProject();
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

        <div className="relative mt-7 grid gap-8 pt-4 md:grid-cols-3 md:gap-5">
          <div
            aria-hidden="true"
            className="absolute left-[16.67%] right-[16.67%] top-4 hidden h-px bg-gradient-to-r from-blue-300 via-violet-300 to-emerald-300 dark:from-blue-800 dark:via-violet-800 dark:to-emerald-800 md:block"
          />
          <AssociationSection
            title="Agents"
            kind="agent"
            description="Specialists that reason and act on behalf of the project."
            items={project.agents || []}
            allItems={allAgents}
            onAdd={handleAddAgent}
            onRemove={handleRemoveAgent}
            addLabel="Add Agent"
            selectPlaceholder="Select an agent..."
          />
          <AssociationSection
            title="Skills"
            kind="skill"
            description="Reusable instructions that sharpen how agents work."
            items={project.skills || []}
            allItems={allSkills}
            onAdd={handleAddSkill}
            onRemove={handleRemoveSkill}
            addLabel="Add Skill"
            selectPlaceholder="Select a skill..."
          />
          <AssociationSection
            title="MCP Instances"
            kind="mcp"
            description="Live connections to tools, services, and external data."
            items={project.mcp_instances || []}
            allItems={allMcpInstances}
            onAdd={handleAddMcp}
            onRemove={handleRemoveMcp}
            addLabel="Add MCP Instance"
            selectPlaceholder="Select an MCP instance..."
          />
        </div>
      </section>
    </div>
  );
}
