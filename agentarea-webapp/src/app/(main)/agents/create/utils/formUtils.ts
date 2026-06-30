import { FieldErrors } from "react-hook-form";

/**
 * Retrieve nested error message from react-hook-form errors object
 */
export function getNestedErrorMessage(
  errors: FieldErrors<Record<string, unknown>>,
  path: string
): string | undefined {
  const keys = path.split(".");
  let current: unknown = errors;

  for (const key of keys) {
    if (current && typeof current === "object" && key in current) {
      current = (current as Record<string, unknown>)[key];
    } else {
      return undefined;
    }
  }

  if (
    current &&
    typeof current === "object" &&
    "message" in current &&
    typeof current.message === "string"
  ) {
    return current.message;
  }

  if (typeof current === "string") {
    return current;
  }

  return undefined;
}
