// Every spec id, workspace or catalog, is a UUID; the list endpoint rejects
// anything else, and any other value could not name a spec anyway.
const SPEC_ID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** The most ids `GET /mcp-servers/?ids=` accepts in one request. */
export const SPEC_IDS_PER_REQUEST = 100;

/**
 * The distinct spec ids among `specIds` (typically instances'
 * `server_spec_id`), split into requests the list endpoint accepts. A page asks
 * for exactly these rather than reading the first page of the spec list and
 * hoping every instance's spec is on it.
 */
export function specIdBatches(
  specIds: readonly (string | null | undefined)[],
  batchSize: number = SPEC_IDS_PER_REQUEST
): string[][] {
  const ids = [
    ...new Set(
      specIds.filter((id): id is string => typeof id === "string" && SPEC_ID.test(id))
    ),
  ];
  const batches: string[][] = [];
  for (let start = 0; start < ids.length; start += batchSize) {
    batches.push(ids.slice(start, start + batchSize));
  }
  return batches;
}
