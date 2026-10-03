import type { ClientResponse } from "@/api/client/types.gen";
import {
  apiErrorMessage,
  formatApiError,
  type ApiResultLike,
} from "@/lib/api-errors";
import ClientsClient from "./ClientsClient";

export default async function ClientsData({
  initialResult,
  loadFailedLabel,
}: {
  initialResult: Promise<
    { apiResult: ApiResultLike<ClientResponse[]> } | { exception: unknown }
  >;
  loadFailedLabel: string;
}) {
  let initialData: ClientResponse[] = [];
  let initialLoadError: string | null = null;

  const result = await initialResult;
  if ("exception" in result) {
    console.error("Failed to load harnesses", result.exception);
    initialLoadError = `${loadFailedLabel}: ${formatApiError(result.exception)}`;
  } else if (result.apiResult.error || !result.apiResult.data) {
    initialLoadError = apiErrorMessage(result.apiResult, loadFailedLabel);
  } else {
    initialData = result.apiResult.data;
  }

  return (
    <ClientsClient
      initialData={initialData}
      initialLoadError={initialLoadError}
    />
  );
}
