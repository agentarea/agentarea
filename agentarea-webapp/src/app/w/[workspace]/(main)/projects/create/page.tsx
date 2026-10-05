import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import ProjectForm from "../shared/ProjectForm";
import CreateProjectHeaderControls from "./CreateProjectHeaderControls";

export const metadata: Metadata = {
  title: "Create Project",
};

export default async function CreateProjectPage() {
  const t = await getTranslations("ProjectsPage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/projects" },
          { label: t("create.title") },
        ],
        controls: <CreateProjectHeaderControls />,
      }}
    >
      <ProjectForm />
    </ContentBlock>
  );
}
