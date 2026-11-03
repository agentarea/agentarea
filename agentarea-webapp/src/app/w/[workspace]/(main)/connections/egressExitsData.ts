import { getTranslations } from "next-intl/server";
import { apiErrorMessage } from "@/lib/api-errors";
import { getEgressExits } from "@/lib/egress-exits";
import { toEgressExitOptions, type EgressExitChoices } from "./egress-exit";

/**
 * The exits a container connection may leave through, or null on a deployment
 * that has none, where the connection pages show nothing about exits. A failed
 * load is a message for the page to show.
 */
export async function loadEgressExitChoices(): Promise<EgressExitChoices | null> {
  const [state, t] = await Promise.all([
    getEgressExits(),
    getTranslations("EgressExits"),
  ]);
  if (state.status === "none") return null;
  if (state.status === "error") {
    return {
      ok: false,
      message: apiErrorMessage(state.failure, t("loadFailed")),
    };
  }
  return { ok: true, exits: toEgressExitOptions(state.exits) };
}
