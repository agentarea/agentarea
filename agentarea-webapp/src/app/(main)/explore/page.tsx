import type { Metadata } from "next";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import { fetchCatalogPage } from "@/lib/api";
import CatalogGallery, {
  ExplorePendingProvider,
  ExploreTypeTabs,
  ExploreViewToggle,
} from "../bundles/components/CatalogGallery";
import {
  EXPLORE_VIEW_COOKIE,
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

  // Persisted grid/table choice: URL param wins, otherwise the cookie written
  // by the view toggle, otherwise grid. Seeds the toggle + gallery defaults so
  // the user's last view is restored on return.
  const cookieStore = await cookies();
  const initialView =
    sp.view === "table" || sp.view === "grid"
      ? sp.view
      : cookieStore.get(EXPLORE_VIEW_COOKIE)?.value === "table"
        ? "table"
        : "grid";

  const { items, hasMore, error } = await fetchCatalogPage(type, 0, PAGE);
  const entries: CatalogEntry[] = (items as RegistryItem[]).map((it) =>
    normalize(type, it)
  );

  return (
    // Provider wraps both the subheader (type tabs trigger the transition) and
    // the content (gallery skeletons on isPending) so the switch is flash-free.
    <ExplorePendingProvider>
      <ContentBlock
        header={{
          breadcrumb: [{ label: "Explore" }],
          description:
            "Browse the catalog. Filter by type, use case, or integration, then add to your workspace.",
        }}
        subheader={
          <>
            <ExploreTypeTabs initialType={type} />
            <ExploreViewToggle initialView={initialView} />
          </>
        }
      >
        <CatalogGallery
          initialType={type}
          initialEntries={entries}
          initialHasMore={hasMore}
          initialError={error ? "Failed to load catalog." : null}
          initialView={initialView}
        />
      </ContentBlock>
    </ExplorePendingProvider>
  );
}
