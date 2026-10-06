import { useTranslations } from "next-intl";
import EmptyState from "@/components/EmptyState";

/** No projects yet: what one is for, and the way to the create page. */
export function ProjectsEmptyState() {
  const t = useTranslations("ProjectsPage.empty");

  return (
    <EmptyState
      title={t("title")}
      description={t("description")}
      hints={[
        { text: t("hintAgents") },
        { text: t("hintSkills") },
        { text: t("hintFiles") },
      ]}
      iconsType="agent"
      action={{ label: t("action"), href: "/projects/create" }}
    />
  );
}
