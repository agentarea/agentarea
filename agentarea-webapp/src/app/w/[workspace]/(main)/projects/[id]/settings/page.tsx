import type { Metadata } from "next";
import { getProject } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import ProjectForm from "../../shared/ProjectForm";

export const metadata: Metadata = {
  title: "Project Settings",
};

interface Props {
  params: Promise<{ id: string }>;
}

/** Editing a project is the form that created it, filled in. */
export default async function ProjectSettingsPage({ params }: Props) {
  const { id } = await params;
  const project = requireApiData(await getProject(id), "project");

  return (
    <div className="px-4 py-5">
      <ProjectForm project={project} />
    </div>
  );
}
