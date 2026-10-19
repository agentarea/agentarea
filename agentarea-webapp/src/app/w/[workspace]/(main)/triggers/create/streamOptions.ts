import type { StreamResponse } from "@/api/client/types.gen";
import {
  listStreams,
  listStreamSources,
  listStreamSourceTypes,
} from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { streamContinuesSessions } from "@/lib/sourceTypes";

/**
 * A stream a trigger can bind to, and whether a trigger on it continues
 * sessions by default: on when a source feeding it is of a type that names the
 * session an event belongs to.
 */
export type StreamOption = StreamResponse & { continuesSessions: boolean };

/** The streams a stream trigger can bind to, or why they could not be listed. */
export type StreamOptions = { items: StreamOption[]; error: string | null };

export async function loadStreamOptions(
  failureLabel: string
): Promise<StreamOptions> {
  const [streams, types] = await Promise.all([
    listStreams(),
    listStreamSourceTypes(),
  ]);
  if (!streams.data) {
    return { items: [], error: apiErrorMessage(streams, failureLabel) };
  }
  if (!types.data) {
    return { items: [], error: apiErrorMessage(types, failureLabel) };
  }
  const catalog = types.data;
  const sources = await Promise.all(
    streams.data.map((stream) => listStreamSources(stream.id))
  );
  const failed = sources.find((result) => !result.data);
  if (failed) {
    return { items: [], error: apiErrorMessage(failed, failureLabel) };
  }
  return {
    items: streams.data.map((stream, index) => ({
      ...stream,
      continuesSessions: streamContinuesSessions(
        catalog,
        (sources[index].data ?? []).map((source) => source.source_type)
      ),
    })),
    error: null,
  };
}
