import {
  mergeUiPrefs,
  parseUiPrefs,
  UI_PREFS_COOKIE,
  UI_PREFS_MAX_AGE,
  type UiPrefs,
  type UiPrefsPatch,
} from "./ui-prefs";

function readUiPrefs(): UiPrefs {
  const prefix = `${UI_PREFS_COOKIE}=`;
  const entry = document.cookie
    .split("; ")
    .find((part) => part.startsWith(prefix));
  return parseUiPrefs(
    entry ? decodeURIComponent(entry.slice(prefix.length)) : undefined
  );
}

export function updateUiPrefs(patch: UiPrefsPatch) {
  const next = mergeUiPrefs(readUiPrefs(), patch);
  document.cookie = `${UI_PREFS_COOKIE}=${encodeURIComponent(JSON.stringify(next))}; path=/; max-age=${UI_PREFS_MAX_AGE}; SameSite=Lax`;
}

export function getUiView(key: string): string | undefined {
  return readUiPrefs().views[key];
}

export function setUiView(key: string, value: string) {
  updateUiPrefs({ views: { [key]: value } });
}
