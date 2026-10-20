import { useTranslations } from "next-intl";
import {
  apiErrorDetail,
  apiErrorMessage,
  catalogFetchFailure,
  type ApiResultLike,
} from "@/lib/api-errors";

/**
 * The message for a failed catalog install or update: what kind of refusal it
 * was, then the server's own words about it.
 */
export function useCatalogFetchError() {
  const t = useTranslations("CatalogFetchErrors");
  return (result: ApiResultLike, label: string) => {
    const failure = catalogFetchFailure(result);
    return failure
      ? `${t(failure)}: ${apiErrorDetail(result, label)}`
      : apiErrorMessage(result, label);
  };
}
