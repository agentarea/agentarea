"use client";

import { useEffect, useState } from "react";
import { useParams } from "next/navigation";
import { DetailSkeleton } from "@/components/Skeleton";
import { AssociationSection } from "./components/AssociationSection";
import { useToast } from "@/hooks/use-toast";
import {
  getProjectAction,
  addAgentToProjectAction,
  removeAgentFromProjectAction,
  addSkillToProjectAction,
  removeSkillFromProjectAction,
  addMcpInstanceToProjectAction,
  removeMcpInstanceFromProjectAction,
  listAgentsAction,
  listSkillsAction,
  listMCPServerInstancesAction,
} from "@/lib/server-actions";

export default function ProjectOverviewPage() {
  const params = useParams();
  const projectId = params.id as string;
  const { toast } = useToast();

  const [project, setProject] = useState<any>(null);
  const [loading, setLoading] = useState(true);
  const [allAgents, setAllAgents] = useState<any[]>([]);
  const [allSkills, setAllSkills] = useState<any[]>([]);
  const [allMcpInstances, setAllMcpInstances] = useState<any[]>([]);

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
        setAllAgents((agentsRes.data as any[]) || []);
        setAllSkills((skillsRes.data as any[]) || []);
        setAllMcpInstances((mcpRes.data as any[]) || []);
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
      toast({ title: "Error", description: "Failed to add agent", variant: "destructive" });
      throw error;
    }
    toast({ title: "Agent added" });
    await fetchProject();
  };

  const handleRemoveAgent = async (agentId: string) => {
    const { error } = await removeAgentFromProjectAction(projectId, agentId);
    if (error) {
      toast({ title: "Error", description: "Failed to remove agent", variant: "destructive" });
      throw error;
    }
    toast({ title: "Agent removed" });
    await fetchProject();
  };

  const handleAddSkill = async (skillId: string) => {
    const { error } = await addSkillToProjectAction(projectId, skillId);
    if (error) {
      toast({ title: "Error", description: "Failed to add skill", variant: "destructive" });
      throw error;
    }
    toast({ title: "Skill added" });
    await fetchProject();
  };

  const handleRemoveSkill = async (skillId: string) => {
    const { error } = await removeSkillFromProjectAction(projectId, skillId);
    if (error) {
      toast({ title: "Error", description: "Failed to remove skill", variant: "destructive" });
      throw error;
    }
    toast({ title: "Skill removed" });
    await fetchProject();
  };

  const handleAddMcp = async (mcpId: string) => {
    const { error } = await addMcpInstanceToProjectAction(projectId, mcpId);
    if (error) {
      toast({ title: "Error", description: "Failed to add MCP instance", variant: "destructive" });
      throw error;
    }
    toast({ title: "MCP instance added" });
    await fetchProject();
  };

  const handleRemoveMcp = async (mcpId: string) => {
    const { error } = await removeMcpInstanceFromProjectAction(projectId, mcpId);
    if (error) {
      toast({ title: "Error", description: "Failed to remove MCP instance", variant: "destructive" });
      throw error;
    }
    toast({ title: "MCP instance removed" });
    await fetchProject();
  };

  return (
    <div className="p-6 space-y-6">
      {/* Description and Instructions */}
      {(project.description || project.instructions) && (
        <div className="space-y-4">
          {project.description && (
            <div>
              <h3 className="text-sm font-medium mb-1">Description</h3>
              <p className="text-sm text-muted-foreground">{project.description}</p>
            </div>
          )}
          {project.instructions && (
            <div>
              <h3 className="text-sm font-medium mb-1">Instructions</h3>
              <p className="text-sm text-muted-foreground whitespace-pre-wrap">{project.instructions}</p>
            </div>
          )}
        </div>
      )}

      {/* Associations */}
      <div className="grid gap-6 md:grid-cols-3">
        <AssociationSection
          title="Agents"
          items={project.agents || []}
          allItems={allAgents}
          onAdd={handleAddAgent}
          onRemove={handleRemoveAgent}
          addLabel="Add Agent"
          selectPlaceholder="Select an agent..."
        />
        <AssociationSection
          title="Skills"
          items={project.skills || []}
          allItems={allSkills}
          onAdd={handleAddSkill}
          onRemove={handleRemoveSkill}
          addLabel="Add Skill"
          selectPlaceholder="Select a skill..."
        />
        <AssociationSection
          title="MCP Instances"
          items={project.mcp_instances || []}
          allItems={allMcpInstances}
          onAdd={handleAddMcp}
          onRemove={handleRemoveMcp}
          addLabel="Add MCP Instance"
          selectPlaceholder="Select an MCP instance..."
        />
      </div>
    </div>
  );
}
