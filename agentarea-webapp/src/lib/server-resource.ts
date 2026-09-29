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

/**
 * For a resource the page can render without: a 403 or 404 yields `null`
 * (logged with the error), anything else still throws like `requireApiData`.
 */
export function optionalApiData<T>(
  result: ApiResultLike<T>,
  resourceName: string
): NonNullable<T> | null {
  if (result.data != null) return result.data as NonNullable<T>;

  const status = getApiStatus(result);
  if (status === 403 || status === 404) {
    console.warn(
      `Rendering without ${resourceName} (${status}): ${formatApiError(result)}`
    );
    return null;
  }

  throw new Error(
    `Failed to load ${resourceName}${status ? ` (${status})` : ""}: ${formatApiError(result)}`
  );
}

export function notFoundOnApi404(error: unknown) {
  if (isApiNotFound(error)) {
    notFound();
  }
}
