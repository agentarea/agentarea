import Link from "next/link";
import { useTranslations } from "next-intl";
import { Plus } from "lucide-react";
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
        controls: (
          <div className="flex items-center gap-2 py-1">
            <Button asChild size="xs" variant="outline">
              <Link href="/skills">{t("cancel")}</Link>
            </Button>
            <Button size="xs" type="submit" form="create-skill-form">
              <Plus className="h-3.5 w-3.5" />
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
