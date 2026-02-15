import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import SettingsClient from "./SettingsClient";

export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Metadata");
  return { title: t("settings") };
}

export default function SettingsPage() {
  return <SettingsClient />;
}
