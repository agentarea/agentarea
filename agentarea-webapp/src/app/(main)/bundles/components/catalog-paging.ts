// Paging state for the catalog gallery, as a pure reducer.
//
// Filtering, sorting and paging are the server's job (see
// /v1/registries/catalog/browse): a single offset only means something over one
// ordered result set, and a client can only sort or filter the prefix it has
// already fetched. What is left here is the bookkeeping around fetching that
// result set page by page -- and that bookkeeping is where the gallery's loader
// used to go wrong, so it lives apart from the component and is tested directly.

import type { CatalogEntry } from "./catalog-data";

export type CategoryFacet = { value: string; count: number };

export type CatalogPaging = {
  entries: CatalogEntry[];
  /** How many items match the current filters across the whole catalog. */
  total: number;
  categories: CategoryFacet[];
  status: "idle" | "loading" | "appending";
  error: string | null;
  /** Set when the server returns an empty page despite claiming more exist. */
  drained: boolean;
};

export type CatalogPagingAction =
  | {
      type: "seed";
      entries: CatalogEntry[];
      total: number;
      categories: CategoryFacet[];
      error?: string | null;
    }
  | { type: "reload" }
  | { type: "appendStart" }
  | { type: "append"; entries: CatalogEntry[]; total: number; categories: CategoryFacet[] }
  | { type: "fail"; error: string };

export function initialPaging(): CatalogPaging {
  return {
    entries: [],
    total: 0,
    categories: [],
    status: "idle",
    error: null,
    drained: false,
  };
}

/** Is there anything left to fetch under the current filters? */
export function hasMore(state: CatalogPaging): boolean {
  return !state.drained && state.entries.length < state.total;
}

/**
 * May we start another page fetch right now?
 *
 * The scroll sentinel stays inside the viewport while a short page renders, so
 * without an in-flight guard it fires page after page. A failure also blocks:
 * the retry is the user's call, not an automatic hammer on a failing endpoint.
 */
export function canFetchMore(state: CatalogPaging): boolean {
  return hasMore(state) && state.status === "idle" && state.error === null;
}

function dedupe(existing: CatalogEntry[], incoming: CatalogEntry[]): CatalogEntry[] {
  const seen = new Set(existing.map((e) => e.id));
  return incoming.filter((e) => !seen.has(e.id));
}

export function catalogPagingReducer(
  state: CatalogPaging,
  action: CatalogPagingAction
): CatalogPaging {
  switch (action.type) {
    case "seed":
      return {
        entries: action.entries,
        total: action.total,
        categories: action.categories,
        status: "idle",
        error: action.error ?? null,
        drained: false,
      };

    case "reload":
      // Filters changed: the current page is meaningless, but the facets stay
      // on screen so the sidebar doesn't collapse and re-expand mid-switch.
      return { ...state, entries: [], error: null, status: "loading", drained: false };

    case "appendStart":
      return { ...state, status: "appending" };

    case "append": {
      // Append only. The server owns the order; re-sorting here is what spliced
      // freshly loaded items into the middle of the rendered list.
      const fresh = dedupe(state.entries, action.entries);
      return {
        ...state,
        entries: fresh.length > 0 ? [...state.entries, ...fresh] : state.entries,
        total: action.total,
        categories: action.categories,
        status: "idle",
        error: null,
        // A page that adds nothing while the total still claims more means the
        // two disagree; stop rather than spin.
        drained: fresh.length === 0,
      };
    }

    case "fail":
      // Keep what is rendered and keep `total`: a transient failure is not the
      // end of the catalog, it is a retry.
      return { ...state, status: "idle", error: action.error };
  }
}
