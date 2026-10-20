import type { SourceTypeResponse } from "@/api/client/types.gen";

/**
 * The workspace's platform stream (ADR-0040 §5): the platform writes its tasks'
 * outcomes there. Members read it and put triggers on it; nobody adds a source
 * to it, and no catalog entry of its kind is offered as a source.
 */
export function isPlatformStream(stream: { kind: string }): boolean {
  return stream.kind === "platform";
}

export function memberSourceTypes(
  types: readonly SourceTypeResponse[]
): SourceTypeResponse[] {
  return types.filter((type) => type.delivery !== "platform");
}
