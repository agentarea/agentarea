import EmptyState from "@/components/EmptyState";
import { listProjects } from "@/lib/api";
import ProjectCard from "./ProjectCard";

interface ProjectsContentProps {
  searchQuery?: string;
}

export default async function ProjectsContent({
  searchQuery = "",
}: ProjectsContentProps) {
  const { data: projects = [] } = await listProjects();

  let filteredProjects = projects as any[];
  if (searchQuery.trim()) {
    const query = searchQuery.toLowerCase();
    filteredProjects = filteredProjects.filter(
      (project) =>
        project.name?.toLowerCase().includes(query) ||
        project.description?.toLowerCase().includes(query)
    );
  }

  if ((projects as any[]).length === 0) {
    return (
      <EmptyState
        title="No projects yet"
        description="Create a project to organize your agents, skills, and tools"
        iconsType="agent"
      />
    );
  }

  if (filteredProjects.length === 0) {
    return (
      <EmptyState
        title="No matching projects"
        description={`No projects found matching: "${searchQuery}"`}
        iconsType="agent"
      />
    );
  }

  return (
    <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 p-4">
      {filteredProjects.map((project) => (
        <ProjectCard key={project.id} project={project} />
      ))}
    </div>
  );
}
