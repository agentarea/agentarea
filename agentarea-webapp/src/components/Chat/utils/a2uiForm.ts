import { applyJsonPointer } from "@/lib/events/a2ui";
import type { A2UIAction } from "../types";

/** JSON Pointer (RFC 6901) lookup; a missing segment resolves to undefined. */
export function resolvePointer(obj: unknown, pointer: string): unknown {
  const parts = (pointer || "/")
    .replace(/^\//, "")
    .split("/")
    .map((p) => p.replace(/~1/g, "/").replace(/~0/g, "~"));
  return parts.reduce(
    (cur: unknown, key): unknown =>
      cur != null && typeof cur === "object" && Object.hasOwn(cur, key)
        ? (cur as Record<string, unknown>)[key]
        : undefined,
    obj
  );
}

/**
 * Write a bound input's value into a copy of the surface's data model. The
 * surface keeps the model the agent sent; edits live in the copy until an
 * action sends them.
 */
export function setBoundValue(
  model: Record<string, unknown>,
  path: string,
  value: unknown
): Record<string, unknown> {
  const next = { ...model };
  applyJsonPointer(next, path, value);
  return next;
}

export function selectedChoices(value: unknown): string[] {
  if (Array.isArray(value)) return value;
  return typeof value === "string" ? [value] : [];
}

export function toggleChoice(
  selected: string[],
  option: string,
  multiple: boolean
): string[] {
  if (!multiple) return [option];
  return selected.includes(option)
    ? selected.filter((item) => item !== option)
    : [...selected, option];
}

/**
 * The action a button sends, with its context's `{ path }` bindings resolved
 * against the edited data model. A closed form sends nothing.
 */
export function buildButtonAction({
  action,
  dataModel,
  disabled,
}: {
  action: A2UIAction | undefined;
  dataModel: Record<string, unknown>;
  disabled: boolean | undefined;
}): { action: A2UIAction; context: Record<string, unknown> } | null {
  if (!action || disabled) return null;
  const context = Object.fromEntries(
    Object.entries(action.event?.context ?? {}).map(([key, value]) => [
      key,
      value && typeof value === "object" && "path" in value
        ? resolvePointer(dataModel, value.path)
        : value,
    ])
  );
  return { action, context };
}
