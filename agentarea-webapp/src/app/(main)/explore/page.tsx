import type { Metadata } from "next";
import ContentBlock from "@/components/ContentBlock";
import { fetchCatalogPage } from "@/lib/api";
import CatalogGallery from "../bundles/components/CatalogGallery";
import {
  PAGE,
  isCatalogType,
  normalize,
  type CatalogEntry,
  type CatalogType,
  type RegistryItem,
} from "../bundles/components/catalog-data";

export const metadata: Metadata = {
  title: "Explore",
};

interface ExplorePageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

// Unified discovery surface: one faceted gallery across every catalog type
// (bundles, agents, skills, connections). The first page is fetched server-side
// so the gallery paints real data immediately — no client fetch race, no flash
// of the wrong type. Switching tabs round-trips here (nuqs shallow:false) and
// the gallery remounts via `key`, so loaded state can never go stale.
export default async function ExplorePage({ searchParams }: ExplorePageProps) {
  const sp = await searchParams;
  const type: CatalogType = isCatalogType(sp.type) ? sp.type : "bundles";

  const { items, hasMore, error } = await fetchCatalogPage(type, 0, PAGE);
  const entries: CatalogEntry[] = (items as RegistryItem[]).map((it) =>
    normalize(type, it)
  );

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Explore" }],
        description:
          "Browse the catalog. Filter by type, use case, or integration, then add to your workspace.",
      }}
    >
      <CatalogGallery
        key={type}
        initialType={type}
        initialEntries={entries}
        initialHasMore={hasMore}
        initialError={error ? "Failed to load catalog." : null}
      />
    </ContentBlock>
  );
}
