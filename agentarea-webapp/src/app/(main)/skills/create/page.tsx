import { useTranslations } from "next-intl";
import { CreateSkillForm } from "./CreateSkillForm";
import ContentBlock from "@/components/ContentBlock";
import { Button } from "@/components/ui/button";

export default function CreateSkillPage() {
  const t = useTranslations("SkillsPage.create");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: useTranslations("SkillsPage")("title"), href: "/skills" },
          { label: t("title") },
        ],
        description: t("description"),
        backLink: {
          label: useTranslations("SkillsPage")("backToSkills"),
          href: "/skills",
        },
        controls: (
          <div className="flex items-center gap-2 py-1">
            <Button size="xs" type="submit" form="create-skill-form">
              {t("createSkill")}
            </Button>
          </div>
        ),
      }}
    >
      <CreateSkillForm />
    </ContentBlock>
  );
}
