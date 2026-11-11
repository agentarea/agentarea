import "server-only";
import { cookies } from "next/headers";
import { parseUiPrefs, UI_PREFS_COOKIE, type UiPrefs } from "./ui-prefs";

export async function readUiPrefs(): Promise<UiPrefs> {
  const cookieStore = await cookies();
  return parseUiPrefs(cookieStore.get(UI_PREFS_COOKIE)?.value);
}
