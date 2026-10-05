import { getTranslations } from "next-intl/server";
import type { ProjectResponse } from "@/api/client/types.gen";
import EmptyState from "@/components/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { listProjects } from "@/lib/api";
import { deterministicHue } from "@/lib/avatar-hue";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import ProjectCard from "./ProjectCard";
import { ProjectsEmptyState } from "./ProjectsEmptyState";

const ProjectIcon = ENTITY_ICONS.project;

interface ProjectsContentProps {
  searchQuery?: string;
  viewMode?: string;
}

const countOf = (item: unknown[] | undefined) => item?.length ?? 0;

export default async function ProjectsContent({
  searchQuery = "",
  viewMode = "grid",
}: ProjectsContentProps) {
  const t = await getTranslations("ProjectsPage");
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
    return <ProjectsEmptyState />;
  }

  const countCell = (value: unknown[] | undefined) => (
    <span className="text-xs tabular-nums text-muted-foreground">
      {countOf(value)}
    </span>
  );

  const columns = [
    {
      header: t("columns.project"),
      accessor: "name",
      render: (name: string, project: ProjectResponse) => (
        <div className="flex items-center gap-2">
          <EntityAvatar
            size={24}
            hue={deterministicHue(project.id)}
            icon={<ProjectIcon strokeWidth={1.85} />}
            aria-hidden
          />
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
      header: t("columns.agents"),
      accessor: "agents",
      render: countCell,
    },
    {
      header: t("columns.skills"),
      accessor: "skills",
      render: countCell,
    },
    {
      header: t("columns.mcp"),
      accessor: "mcp_instances",
      render: countCell,
    },
    {
      header: t("columns.instructions"),
      accessor: "instructions",
      render: (value: string | null) => (
        <span className="text-xs text-muted-foreground">
          {value ? t("hasInstructions") : "—"}
        </span>
      ),
    },
  ];

  return (
    <GridAndTableViews
      viewMode={viewMode}
      data={filteredProjects}
      columns={columns}
      itemLink={(project: ProjectResponse) => `/projects/${project.id}`}
      // ProjectCard is a LinkedCard: it owns its surface and its link.
      wrapCardContent={false}
      cardContent={(project: ProjectResponse) => (
        <ProjectCard project={project} />
      )}
      emptyState={
        <EmptyState
          title={t("noMatchTitle")}
          description={t("noMatchDescription", { query: searchQuery })}
          iconsType="agent"
          action={{ label: t("clearSearch"), href: "/projects" }}
        />
      }
    />
  );
}
