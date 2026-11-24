/**
 * Interface preferences the server needs for the first paint (sidebar open and
 * width, each list's grid/table choice) live in one cookie as a JSON object.
 * This module only parses and builds it; it runs on the server and the client.
 */
export const UI_PREFS_COOKIE = "aa_ui";
export const UI_PREFS_MAX_AGE = 60 * 60 * 24 * 365;

export type UiPrefs = {
  sidebarOpen?: boolean;
  sidebarWidth?: number;
  /** Remembered view per list, keyed by the list (`tab_tasks`, `view_skills`). */
  views: Record<string, string>;
};

const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === "object" && value !== null && !Array.isArray(value);

/** Reads the decoded cookie value; anything it does not recognise is dropped. */
export function parseUiPrefs(raw: string | undefined): UiPrefs {
  if (!raw) return { views: {} };
  let data: unknown;
  try {
    data = JSON.parse(raw);
  } catch (error) {
    console.warn("Ignoring a malformed UI preferences cookie", error);
    return { views: {} };
  }
  if (!isRecord(data)) return { views: {} };

  const views: Record<string, string> = {};
  if (isRecord(data.views)) {
    for (const [key, value] of Object.entries(data.views)) {
      if (typeof value === "string") views[key] = value;
    }
  }
  return {
    ...(typeof data.sidebarOpen === "boolean" && {
      sidebarOpen: data.sidebarOpen,
    }),
    ...(typeof data.sidebarWidth === "number" &&
      Number.isFinite(data.sidebarWidth) && {
        sidebarWidth: data.sidebarWidth,
      }),
    views,
  };
}

export type UiPrefsPatch = Partial<Omit<UiPrefs, "views">> & {
  views?: Record<string, string>;
};

export function mergeUiPrefs(prefs: UiPrefs, patch: UiPrefsPatch): UiPrefs {
  return {
    ...prefs,
    ...patch,
    views: { ...prefs.views, ...patch.views },
  };
}
