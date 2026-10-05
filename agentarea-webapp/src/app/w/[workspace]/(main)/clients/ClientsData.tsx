import type { ClientResponse } from "@/api/client/types.gen";
import {
  apiErrorMessage,
  formatApiError,
  type ApiResultLike,
} from "@/lib/api-errors";
import ClientsClient from "./ClientsClient";

export default async function ClientsData({
  initialResult,
  initialView,
  loadFailedLabel,
}: {
  initialResult: Promise<
    { apiResult: ApiResultLike<ClientResponse[]> } | { exception: unknown }
  >;
  /** The view the page resolved from `?tab=` or the `tab_clients` cookie. */
  initialView: "grid" | "table";
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
      initialView={initialView}
      initialLoadError={initialLoadError}
    />
  );
}
