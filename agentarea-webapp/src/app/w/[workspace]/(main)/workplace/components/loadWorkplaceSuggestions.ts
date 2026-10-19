import { getTranslations } from "next-intl/server";
import {
  listMCPServerInstances,
  listSkills,
  listStreams,
  listStreamSources,
  listStreamSourceTypes,
} from "@/lib/api";
import type { SourceType } from "@/lib/sourceTypes";
import {
  buildWorkplaceSuggestions,
  type WorkplaceSuggestion,
} from "./workplaceSuggestions";

/**
 * Everything the starter chips need, and nothing the chat needs.
 *
 * These reads are kept apart from the chat's own so the page is not held
 * behind them: the composer, the agent picker and the policy selector decide
 * whether the workplace can be used at all, while the chips are a prompt. The
 * caller passes this promise down unawaited and a <Suspense> fills them in.
 *
 * Failures are swallowed into an empty list on purpose — this is the one place
 * where nothing is the correct answer, because a missing suggestion costs the
 * user nothing and an error boundary over the chat would cost them the page.
 */
export async function loadWorkplaceSuggestions(
  agents: { id: string; name: string }[]
): Promise<WorkplaceSuggestion[]> {
  try {
    const [t, streamsResult, mcpResult, skillsResult, typesResult] =
      await Promise.all([
        getTranslations("Workplace.suggestions"),
        listStreams(),
        listMCPServerInstances(),
        listSkills(),
        listStreamSourceTypes(),
      ]);
    const sourcesResults = await Promise.all(
      (streamsResult.data ?? []).map((stream) => listStreamSources(stream.id))
    );

    // A channel is a source type you talk to: its events belong to a session
    // and the task answers back. The catalog says which types those are; the
    // workspace's sources say which of them something already feeds.
    const channels = (typesResult.data ?? []).filter(
      (type) => type.continues_sessions && type.replies
    );
    const used = new Set(
      sourcesResults.flatMap((result) =>
        (result.data ?? []).map((source) => source.source_type)
      )
    );

    const toChannel = (type: SourceType) => ({
      id: type.slug,
      name: type.name,
      iconUrl: type.icon_url ?? null,
      description: type.description || null,
    });
    const isConnected = (type: SourceType) => used.has(type.slug);

    return buildWorkplaceSuggestions(
      {
        connectedChannels: channels.filter(isConnected).map(toChannel),
        availableChannels: channels
          .filter((type) => !isConnected(type))
          .map(toChannel),
        mcpCount: (mcpResult.data ?? []).length,
        skillCount: (skillsResult.data ?? []).length,
        agents,
      },
      (key, values) => t(key, values)
    );
  } catch (error) {
    console.error("Failed to build workplace suggestions:", error);
    return [];
  }
}
