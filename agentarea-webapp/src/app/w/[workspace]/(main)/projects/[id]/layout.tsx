import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getProject } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import ProjectHeaderControls from "./components/ProjectHeaderControls";
import ProjectHeaderTabs from "./components/ProjectHeaderTabs";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

export default async function ProjectLayout({ params, children }: Props) {
  const { id } = await params;
  const projectResponse = await getProject(id);

  const project = requireApiData(projectResponse, "project");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Projects", href: "/projects" },
          { label: project.name, href: `/projects/${project.id}` },
        ],
        controls: <ProjectHeaderControls projectName={project.name} />,
      }}
      className="p-0"
      subheader={<ProjectHeaderTabs projectId={project.id} />}
    >
      {children}
    </ContentBlock>
  );
}
