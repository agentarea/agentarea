import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import SkillsContentSkeleton from "./components/SkillsContentSkeleton";

export default async function Loading() {
  const t = await getTranslations("SkillsPage");
  return (
    <ContentBlock
      header={{ breadcrumb: [{ label: t("title") }] }}
      className="p-0"
    >
      <SkillsContentSkeleton view="list" />
    </ContentBlock>
  );
}
