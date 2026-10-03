import { getTranslations } from "next-intl/server";
import FilesSkeleton from "./FilesSkeleton";

export default async function Loading() {
  const t = await getTranslations("FilesPage");
  return <FilesSkeleton title={t("title")} />;
}
