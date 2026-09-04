import type { Metadata } from "next";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import { browseCatalog } from "@/lib/api";
import CatalogGallery, {
  ExplorePendingProvider,
  ExploreSortSelect,
  ExploreTypeTabs,
  ExploreViewToggle,
} from "../bundles/components/CatalogGallery";
import {
  ALL,
  DEFAULT_SORT,
  EXPLORE_VIEW_COOKIE,
  PAGE,
  isCatalogType,
  isSortMode,
  normalize,
  type CatalogEntry,
  type CatalogType,
  type RegistryItem,
  type SortMode,
} from "../bundles/components/catalog-data";

export const metadata: Metadata = {
  title: "Explore",
};

interface ExplorePageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

function param(v: string | string[] | undefined): string | undefined {
  return typeof v === "string" && v ? v : undefined;
}

// Unified discovery surface: one faceted gallery across every catalog type
// (bundles, agents, skills, connections).
//
// Every browse dimension — type, search, category, sort — is resolved here and
// applied by the server in one ordered, paged query, so the first page is real
// data on first paint and page N means the same thing as page 1. Changing any
// of them round-trips here (nuqs shallow:false); the gallery re-seeds from the
// new props, so loaded state can never go stale.
export default async function ExplorePage({ searchParams }: ExplorePageProps) {
  const sp = await searchParams;
  const type: CatalogType = isCatalogType(sp.type) ? sp.type : "bundles";
  const query = param(sp.q);
  const categoryParam = param(sp.category);
  const category = categoryParam && categoryParam !== ALL ? categoryParam : undefined;
  const sort: SortMode = isSortMode(sp.sort) ? sp.sort : DEFAULT_SORT;

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

  const { items, total, categories, error } = await browseCatalog({
    registryType: type,
    q: query,
    category,
    sort,
    limit: PAGE,
    offset: 0,
  });
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
            <div className="flex items-center gap-2">
              <ExploreSortSelect initialSort={sort} />
              <ExploreViewToggle initialView={initialView} />
            </div>
          </>
        }
      >
        <CatalogGallery
          initialType={type}
          initialEntries={entries}
          initialTotal={total}
          initialCategories={categories}
          initialError={error ? "Failed to load catalog." : null}
          initialView={initialView}
        />
      </ContentBlock>
    </ExplorePendingProvider>
  );
}
