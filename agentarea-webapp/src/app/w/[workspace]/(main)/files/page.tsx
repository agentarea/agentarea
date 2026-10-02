import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { listWorkspaceFiles } from "@/lib/api";
import FilesData from "./FilesData";
import FilesSkeleton from "./FilesSkeleton";

export default async function WorkspaceFilesPage() {
  const initialResult = listWorkspaceFiles().then(
    (apiResult) => ({ apiResult }),
    (exception: unknown) => ({ exception })
  );
  const t = await getTranslations("FilesPage");

  return (
    <Suspense fallback={<FilesSkeleton title={t("title")} />}>
      <FilesData
        initialResult={initialResult}
        loadFailedLabel={t("loadFailed")}
      />
    </Suspense>
  );
}
