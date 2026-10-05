import type { CatalogEntry, CatalogType, RawSpec } from "./catalog-data";

// The unfiltered catalog opens on a few short shelves above the full list, so
// the entries most workspaces want are visible without scrolling through
// thousands. Every shelf is derived from what the catalog already says about an
// entry -- nothing here names a specific item.

export type CatalogSectionKey = "recommended" | "popular";

export type CatalogSection = {
  key: CatalogSectionKey;
  title: string;
  description: string;
  entries: CatalogEntry[];
};

export const SECTION_SIZE = 8;

/**
 * How many entries of the recommended order the shelves are picked from. The
 * curated skills registry alone holds ~130 entries ahead of the community
 * mirror, so the skill shelves need a longer head to reach the most-starred
 * community skills.
 */
export const SECTION_SOURCE_SIZE: Record<CatalogType, number> = {
  connections: 96,
  skills: 250,
  agents: 96,
  bundles: 96,
};

function stars(entry: CatalogEntry): number {
  const provenance = (entry.spec as RawSpec).provenance as RawSpec | undefined;
  const value = provenance?.stars;
  return typeof value === "number" ? value : 0;
}

function section(
  key: CatalogSectionKey,
  title: string,
  description: string,
  entries: CatalogEntry[]
): CatalogSection[] {
  return entries.length
    ? [{ key, title, description, entries: entries.slice(0, SECTION_SIZE) }]
    : [];
}

/**
 * Shelves for the default view, picked from the head of the catalog in
 * recommended order. An entry appears on one shelf at most; an empty shelf is
 * left out.
 */
export function catalogSections(
  type: CatalogType,
  head: CatalogEntry[]
): CatalogSection[] {
  if (type === "connections") {
    // Verified = a curated connection whose sign-in flow was checked end to end.
    const recommended = head.filter((e) => e.verified).slice(0, SECTION_SIZE);
    const taken = new Set(recommended.map((e) => e.id));
    // The published order leads with the official integrations.
    const popular = head.filter((e) => !taken.has(e.id));
    return [
      ...section(
        "recommended",
        "Recommended",
        "Verified connections with a checked sign-in flow.",
        recommended
      ),
      ...section(
        "popular",
        "Popular",
        "Official integrations most workspaces connect.",
        popular
      ),
    ];
  }
  if (type === "skills") {
    // The curated skills registry outranks the community mirror, so the head
    // of the recommended order is the hand-picked set.
    const recommended = head.slice(0, SECTION_SIZE);
    const taken = new Set(recommended.map((e) => e.id));
    const popular = head
      .filter((e) => !taken.has(e.id) && stars(e) > 0)
      .sort((a, b) => stars(b) - stars(a));
    return [
      ...section(
        "recommended",
        "Recommended",
        "Hand-picked skills to start with.",
        recommended
      ),
      ...section(
        "popular",
        "Popular",
        "The most-starred skills on GitHub.",
        popular
      ),
    ];
  }
  return section(
    "recommended",
    "Recommended",
    "Featured by the AgentArea team.",
    head.filter((e) => e.featured)
  );
}

/** The shelves only belong to the unfiltered catalog in its own order. */
export function showsSections(params: {
  query: string;
  category: string | null | undefined;
  protocol: string | null | undefined;
  hosting?: string | null | undefined;
  sort: string;
  all: string;
}): boolean {
  const unset = (v: string | null | undefined) => !v || v === params.all;
  return (
    params.query.trim() === "" &&
    unset(params.category) &&
    unset(params.protocol) &&
    unset(params.hosting) &&
    params.sort === "recommended"
  );
}
