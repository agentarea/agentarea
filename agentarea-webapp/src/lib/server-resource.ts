import { notFound } from "next/navigation";
import {
  formatApiError,
  getApiStatus,
  isApiNotFound,
  type ApiResultLike,
} from "./api-errors";

export function requireApiData<T>(
  result: ApiResultLike<T>,
  resourceName: string
): NonNullable<T> {
  if (result.data != null) return result.data as NonNullable<T>;

  if (isApiNotFound(result)) {
    notFound();
  }

  const status = getApiStatus(result);
  const statusText = status ? ` (${status})` : "";
  throw new Error(
    `Failed to load ${resourceName}${statusText}: ${formatApiError(result)}`
  );
}

export function notFoundOnApi404(error: unknown) {
  if (isApiNotFound(error)) {
    notFound();
  }
}
