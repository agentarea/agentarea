"use server";

import {
  zListRegistriesV1RegistriesGetResponse,
  zListRegistryItemsV1RegistriesRegistryIdItemsGetResponse,
} from "@/api/client/zod.gen";
import {
  normalize,
  TYPE_KEYS,
  type CatalogType,
  type RawSpec,
  type RegistryItem,
} from "@/app/(main)/bundles/components/catalog-data";
import { browseCatalog, listRegistries, listRegistryItems } from "@/lib/api";

const CURATED_SKILLS_SOURCE =
  "https://agentarea-mcp-registry.s3.amazonaws.com/registry/system/skills.json";

export type CatalogSuggestionItem = {
  id: string;
  title: string;
  description: string;
  iconUrl: string | null;
  source: string | null;
  popularityLabel: string | null;
};

function errorMessage(error: unknown, fallback: string): string {
  if (!error) return fallback;
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  if (typeof error === "object" && "detail" in error) {
    const detail = (error as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

function assertCatalogType(type: CatalogType): CatalogType {
  if (!TYPE_KEYS.includes(type)) {
    throw new Error("Invalid catalog type");
  }
  return type;
}

function popularity(item: RegistryItem): number {
  const provenance = item.spec?.provenance as RawSpec | undefined;
  const exact = provenance?.stars;
  if (typeof exact === "number" && Number.isFinite(exact) && exact >= 0) {
    return exact;
  }
  const bucket = item.tags
    .map((tag) => /^stars:(\d+)\+$/.exec(tag)?.[1])
    .find(Boolean);
  return bucket ? Number(bucket) : 0;
}

function formatPopularity(stars: number): string | null {
  if (stars <= 0) return null;
  if (stars < 1_000) return `${stars} stars`;
  const value = stars / 1_000;
  return `${value >= 100 ? value.toFixed(0) : value.toFixed(1)}K stars`;
}

function toSuggestions(
  type: CatalogType,
  items: RegistryItem[],
  max: number,
  rankByPopularity: boolean
): CatalogSuggestionItem[] {
  const ranked = items.map((item) => ({
    item,
    entry: normalize(type, item),
    stars: popularity(item),
  }));
  if (rankByPopularity) {
    ranked.sort(
      (a, b) => b.stars - a.stars || a.entry.title.localeCompare(b.entry.title)
    );
  }

  const seen = new Set<string>();
  const suggestions: CatalogSuggestionItem[] = [];
  for (const { item, entry, stars } of ranked) {
    const title = entry.title.trim();
    const description = entry.description.trim();
    if (
      title.toLocaleLowerCase() === "unknown" ||
      !/\p{L}/u.test(title) ||
      description.length < 24
    ) {
      continue;
    }
    const provenance = item.spec?.provenance as RawSpec | undefined;
    const source =
      typeof provenance?.repo === "string"
        ? provenance.repo
        : type === "skills"
          ? (entry.meta[0] ?? null)
          : null;
    const key = `${title.toLocaleLowerCase()}|${source ?? ""}`;
    if (seen.has(key)) continue;
    seen.add(key);
    suggestions.push({
      id: entry.id,
      title,
      description,
      iconUrl: entry.iconUrl,
      source,
      popularityLabel: formatPopularity(stars),
    });
    if (suggestions.length === max) break;
  }
  return suggestions;
}

export async function listCatalogSuggestionsAction(
  type: CatalogType,
  max: number
): Promise<CatalogSuggestionItem[]> {
  const registryType = assertCatalogType(type);
  if (registryType === "skills") {
    const { data: registriesData, error: registriesError } =
      await listRegistries({
        registry_type: registryType,
        active_only: true,
      });
    if (registriesError || !registriesData) {
      throw new Error(
        errorMessage(registriesError, "Failed to load registries")
      );
    }
    const registries =
      zListRegistriesV1RegistriesGetResponse.parse(registriesData);
    const curated = registries.find(
      (registry) => registry.source_url === CURATED_SKILLS_SOURCE
    );
    if (curated) {
      const { data, error } = await listRegistryItems(curated.id, {
        limit: 200,
        offset: 0,
      });
      if (error || !data) {
        throw new Error(errorMessage(error, "Failed to load catalog items"));
      }
      const items =
        zListRegistryItemsV1RegistriesRegistryIdItemsGetResponse.parse(
          data
        ) as RegistryItem[];
      return toSuggestions(registryType, items, max, true);
    }
  }

  const result = await browseCatalog({
    registryType,
    sort: "featured",
    limit: Math.max(max * 4, max),
    offset: 0,
  });
  if (result.error) {
    throw new Error(errorMessage(result.error, "Failed to load catalog items"));
  }
  return toSuggestions(
    registryType,
    result.items as RegistryItem[],
    max,
    false
  );
}
