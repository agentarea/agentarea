import type { TriggerResponse } from "@/api/client/types.gen";
import {
  listMCPServerInstances,
  listSkills,
  listTriggerCatalog,
  listTriggers,
} from "@/lib/api";
import {
  buildWorkplaceSuggestions,
  type WorkplaceSuggestion,
} from "./workplaceSuggestions";

type CatalogEntry = {
  id?: string;
  name?: string;
  kind?: string;
  icon_url?: string | null;
  data_extractor?: string | null;
};

/**
 * Everything the starter chips need, and nothing the chat needs.
 *
 * These four reads are kept apart from the chat's own so the page is not held
 * behind them: the composer, the agent picker and the policy selector decide
 * whether the workplace can be used at all, while the chips are a prompt. The
 * caller passes this promise down unawaited and a <Suspense> fills them in.
 *
 * Failures are swallowed into an empty list on purpose — this is the one place
 * where nothing is the correct answer, because a missing suggestion costs the
 * user nothing and an error boundary over the chat would cost them the page.
 */
export async function loadWorkplaceSuggestions(
  agentNames: string[]
): Promise<WorkplaceSuggestion[]> {
  try {
    const [triggersResult, mcpResult, skillsResult, catalogResult] =
      await Promise.all([
        listTriggers(),
        listMCPServerInstances(),
        listSkills(),
        listTriggerCatalog(),
      ]);

    // The catalog names and draws every channel; the triggers only say which of
    // them something is already listening on.
    const messaging = ((catalogResult.data ?? []) as CatalogEntry[]).filter(
      (entry) => entry.kind === "messaging"
    );

    const listening = new Set(
      ((triggersResult.data ?? []) as TriggerResponse[])
        .map((trigger) => trigger.data_extractor)
        .filter(Boolean)
        .map(String)
    );

    const toChannel = (entry: CatalogEntry) => ({
      id: String(entry.id ?? entry.data_extractor ?? entry.name ?? ""),
      name: String(entry.name ?? entry.data_extractor ?? ""),
      iconUrl: entry.icon_url ?? null,
    });
    const isConnected = (entry: CatalogEntry) =>
      Boolean(entry.data_extractor) &&
      listening.has(String(entry.data_extractor));

    return buildWorkplaceSuggestions({
      connectedChannels: messaging.filter(isConnected).map(toChannel),
      availableChannels: messaging.filter((e) => !isConnected(e)).map(toChannel),
      mcpCount: (mcpResult.data ?? []).length,
      skillCount: (skillsResult.data ?? []).length,
      agentNames,
    });
  } catch (error) {
    console.error("Failed to build workplace suggestions:", error);
    return [];
  }
}
