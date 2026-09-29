import { useTranslations } from "next-intl";
import { CreateSkillForm } from "./CreateSkillForm";
import CreateSkillHeaderControls from "./CreateSkillHeaderControls";
import ContentBlock from "@/components/ContentBlock";

export default function CreateSkillPage() {
  const t = useTranslations("SkillsPage.create");

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: useTranslations("SkillsPage")("title"), href: "/skills" },
          { label: t("title") },
        ],
        controls: <CreateSkillHeaderControls />,
      }}
    >
      <CreateSkillForm />
    </ContentBlock>
  );
}
