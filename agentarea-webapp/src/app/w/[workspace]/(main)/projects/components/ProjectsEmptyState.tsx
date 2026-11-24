import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";
import ProjectsScene from "@/components/illustrations/ProjectsScene";

/** No projects yet: what one is for, and the way to the create page. */
export function ProjectsEmptyState() {
  const t = useTranslations("ProjectsPage.empty");

  return (
    <EmptyState
      title={t("title")}
      visual={<ProjectsScene />}
      description={t("description")}
      hints={[
        { text: t("hintAgents") },
        { text: t("hintSkills") },
        { text: t("hintFiles") },
      ]}
      action={{ label: t("action"), href: "/projects/create" }}
    />
  );
}
