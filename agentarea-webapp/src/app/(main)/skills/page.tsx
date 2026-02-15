import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import SkillsClient from "./SkillsClient";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Metadata");
  return { title: t("skills") };
}

export default function SkillsPage() {
  return <SkillsClient />;
}
