import { notFound } from "next/navigation";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getProject } from "@/lib/api";
import ProjectHeaderTabs from "./components/ProjectHeaderTabs";
import ProjectHeaderControls from "./components/ProjectHeaderControls";

interface Props {
  params: Promise<{ id: string }>;
  children: React.ReactNode;
}

export default async function ProjectLayout({ params, children }: Props) {
  const { id } = await params;
  const projectResponse = await getProject(id);

  if (!projectResponse.data) {
    notFound();
  }

  const project = projectResponse.data;

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
