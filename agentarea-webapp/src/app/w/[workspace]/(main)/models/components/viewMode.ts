/**
 * One grid/table choice for both models tabs: the toggle sits in their shared
 * header and stays put while you switch tabs, so it must not flip on its own.
 */
export const MODELS_VIEW_COOKIE = "tab_models";

export type ModelsViewMode = "grid" | "table";

/** URL `?tab=` wins, then the remembered choice, then grid. */
export function resolveViewMode(
  urlTab: unknown,
  fallback: string | undefined
): ModelsViewMode {
  if (urlTab === "grid" || urlTab === "table") return urlTab;
  return fallback === "table" ? "table" : "grid";
}
