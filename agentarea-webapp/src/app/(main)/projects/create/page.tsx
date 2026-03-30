import type { Metadata } from "next";
import ContentBlock from "@/components/ContentBlock";
import { Button } from "@/components/ui/button";
import { CreateProjectForm } from "./CreateProjectForm";

export const metadata: Metadata = {
  title: "Create Project",
};

export default function CreateProjectPage() {
  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Projects", href: "/projects" },
          { label: "Create Project" },
        ],
        description: "Create a new project to organize agents, skills, and tools",
        backLink: {
          label: "Back to Projects",
          href: "/projects",
        },
        controls: (
          <div className="flex items-center gap-2 py-1">
            <Button size="xs" type="submit" form="create-project-form">
              Create Project
            </Button>
          </div>
        ),
      }}
    >
      <CreateProjectForm />
    </ContentBlock>
  );
}
