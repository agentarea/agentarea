import type { WorkspaceFileListResponse } from "@/api/client/types.gen";
import { apiErrorMessage, formatApiError, type ApiResultLike } from "@/lib/api-errors";
import FilesClient from "./FilesClient";

export default async function FilesData({
  initialResult,
  loadFailedLabel,
}: {
  initialResult: Promise<
    | { apiResult: ApiResultLike<WorkspaceFileListResponse> }
    | { exception: unknown }
  >;
  loadFailedLabel: string;
}) {
  let initialData: WorkspaceFileListResponse = { files: [], directories: [] };
  let initialLoadError: string | null = null;

  const result = await initialResult;
  if ("exception" in result) {
    console.error("Failed to load workspace files", result.exception);
    initialLoadError = `${loadFailedLabel}: ${formatApiError(result.exception)}`;
  } else if (result.apiResult.error || !result.apiResult.data) {
    initialLoadError = apiErrorMessage(result.apiResult, loadFailedLabel);
  } else {
    initialData = result.apiResult.data;
  }

  return (
    <FilesClient
      initialData={initialData}
      initialLoadError={initialLoadError}
    />
  );
}
