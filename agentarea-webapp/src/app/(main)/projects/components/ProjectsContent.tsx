import type { ProjectResponse } from "@/api/client/types.gen";
import { FileText } from "lucide-react";
import EmptyState from "@/components/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { Badge } from "@/components/ui/badge";
import { listProjects } from "@/lib/api";
import { ENTITY_ICONS, EntityIcon } from "@/lib/entity-icons";

const AgentIcon = ENTITY_ICONS.agent;
const SkillIcon = ENTITY_ICONS.skill;
const McpIcon = ENTITY_ICONS.mcp;

interface ProjectsContentProps {
  searchQuery?: string;
  searchParams?: { [key: string]: string | string[] | undefined };
}

const countOf = (item: unknown[] | undefined) => item?.length ?? 0;

export default async function ProjectsContent({
  searchQuery = "",
  searchParams = {},
}: ProjectsContentProps) {
  const { data: projects = [] } = await listProjects();

  let filteredProjects = projects as ProjectResponse[];
  if (searchQuery.trim()) {
    const query = searchQuery.toLowerCase();
    filteredProjects = filteredProjects.filter(
      (project) =>
        project.name?.toLowerCase().includes(query) ||
        project.description?.toLowerCase().includes(query)
    );
  }

  if ((projects as ProjectResponse[]).length === 0) {
    return (
      <EmptyState
        title="No projects yet"
        description="Create a project to organize your agents, skills, and tools"
        iconsType="agent"
      />
    );
  }

  const columns = [
    {
      header: "Project",
      accessor: "name",
      render: (name: string, project: ProjectResponse) => (
        <div className="flex items-center gap-2">
          <EntityIcon kind="project" className="text-primary" />
          <div>
            <div className="font-medium">{name}</div>
            {project.description && (
              <div className="mt-1 max-w-md text-xs text-muted-foreground line-clamp-1">
                {project.description}
              </div>
            )}
          </div>
        </div>
      ),
    },
    {
      header: "Agents",
      accessor: "agents",
      render: (value: ProjectResponse["agents"]) => (
        <span className="text-xs text-muted-foreground">{countOf(value)}</span>
      ),
    },
    {
      header: "Skills",
      accessor: "skills",
      render: (value: ProjectResponse["skills"]) => (
        <span className="text-xs text-muted-foreground">{countOf(value)}</span>
      ),
    },
    {
      header: "MCP",
      accessor: "mcp_instances",
      render: (value: ProjectResponse["mcp_instances"]) => (
        <span className="text-xs text-muted-foreground">{countOf(value)}</span>
      ),
    },
    {
      header: "Instructions",
      accessor: "instructions",
      render: (value: string | null) => (
        <span className="text-xs text-muted-foreground">
          {value ? "Yes" : "—"}
        </span>
      ),
    },
  ];

  return (
    <div className="p-4">
      <GridAndTableViews
        searchParams={searchParams}
        routeChange="/projects"
        data={filteredProjects}
        columns={columns}
        itemLink={(project: ProjectResponse) => `/projects/${project.id}`}
        emptyState={
          <EmptyState
            title="No matching projects"
            description={`No projects found matching: "${searchQuery}"`}
            iconsType="agent"
          />
        }
        cardContent={(project: ProjectResponse) => (
          <div className="flex h-full flex-col gap-3">
            <div className="flex items-start gap-2">
              <EntityIcon kind="project" className="mt-0.5 flex-shrink-0 text-primary" />
              <div className="min-w-0 flex-1">
                <div className="truncate text-[16px] font-[500]">{project.name}</div>
                {project.parent_project_id && (
                  <Badge variant="outline" className="mt-1 text-[10px]">
                    sub-project
                  </Badge>
                )}
              </div>
            </div>

            {project.description && (
              <div className="line-clamp-2 text-[14px] opacity-50">
                {project.description}
              </div>
            )}

            {project.instructions && (
              <div className="flex items-start gap-1.5 rounded-md bg-muted/50 px-2 py-1.5 text-xs text-muted-foreground">
                <FileText className="mt-0.5 h-3 w-3 flex-shrink-0" />
                <span className="line-clamp-2">{project.instructions}</span>
              </div>
            )}

            <div className="mt-auto flex items-center gap-3 pt-1 text-xs text-muted-foreground">
              <span className="flex items-center gap-1">
                <AgentIcon className="h-3.5 w-3.5" />
                {countOf(project.agents)}
              </span>
              <span className="flex items-center gap-1">
                <SkillIcon className="h-3.5 w-3.5" />
                {countOf(project.skills)}
              </span>
              <span className="flex items-center gap-1">
                <McpIcon className="h-3.5 w-3.5" />
                {countOf(project.mcp_instances)}
              </span>
            </div>
          </div>
        )}
      />
    </div>
  );
}
