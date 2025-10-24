import { FieldErrors } from "react-hook-form";

/**
 * Retrieve nested error message from react-hook-form errors object
 */
export function getNestedErrorMessage(
  errors: FieldErrors<any>,
  path: string
): string | undefined {
  const keys = path.split(".");
  let current = errors;

  for (const key of keys) {
    if (current && typeof current === "object" && key in current) {
      current = (current as any)[key];
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
