import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { browseCatalog } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import {
  ALL,
  DEFAULT_SORT,
  EXPLORE_VIEW_COOKIE,
  isCatalogProtocol,
  isSortMode,
  normalize,
  PAGE,
  REGISTRY_TYPE,
  toCatalogType,
  type CatalogEntry,
  type CatalogType,
  type RegistryItem,
  type SortMode,
} from "../bundles/components/catalog-data";
import {
  catalogSections,
  SECTION_SOURCE_SIZE,
  showsSections,
} from "../bundles/components/catalog-sections";
import CatalogGallery, {
  ExplorePendingProvider,
  ExploreSortSelect,
  ExploreTypeTabs,
  ExploreViewToggle,
} from "../bundles/components/CatalogGallery";

export const metadata: Metadata = {
  title: "Catalog",
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
  const type: CatalogType = toCatalogType(sp.type) ?? "bundles";
  const query = param(sp.q);
  const categoryParam = param(sp.category);
  const category =
    categoryParam && categoryParam !== ALL ? categoryParam : undefined;
  // Junk in the URL means "unfiltered" rather than an error page.
  const protocol = isCatalogProtocol(sp.protocol) ? sp.protocol : undefined;
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

  // The unfiltered catalog opens on Recommended / Popular shelves above the
  // full list. They are picked from the head of the recommended order, which
  // for most types is the first page itself; skills need a longer head.
  const withSections = showsSections({
    query: query ?? "",
    category,
    protocol,
    sort,
    all: ALL,
  });
  const sourceSize = SECTION_SOURCE_SIZE[type];
  const [
    { items, total, categories, protocols, error, status },
    sectionSource,
  ] = await Promise.all([
    browseCatalog({
      registryType: REGISTRY_TYPE[type],
      q: query,
      category,
      protocol,
      sort,
      limit: PAGE,
      offset: 0,
    }),
    withSections && sourceSize > PAGE
      ? browseCatalog({
          registryType: REGISTRY_TYPE[type],
          sort,
          limit: sourceSize,
          offset: 0,
        })
      : null,
  ]);
  const tBundle = await getTranslations("BundleInstall");
  const t = await getTranslations("CatalogPage");
  const entries: CatalogEntry[] = (items as RegistryItem[]).map((it) =>
    normalize(type, it)
  );
  const sections = withSections
    ? catalogSections(
        type,
        sectionSource
          ? (sectionSource.items as RegistryItem[]).map((it) =>
              normalize(type, it)
            )
          : entries
      )
    : [];

  return (
    // Provider wraps both the subheader (type tabs trigger the transition) and
    // the content (gallery skeletons on isPending) so the switch is flash-free.
    <ExplorePendingProvider>
      <ContentBlock
        header={{
          breadcrumb: [{ label: t("title") }],
          description: t("description"),
        }}
        subheader={
          <SubheaderToolbar
            categories={<ExploreTypeTabs initialType={type} />}
            controls={
              <>
                <ExploreSortSelect initialSort={sort} />
                <ExploreViewToggle initialView={initialView} />
              </>
            }
          />
        }
      >
        <CatalogGallery
          initialType={type}
          initialEntries={entries}
          initialTotal={total}
          initialCategories={categories}
          initialProtocols={protocols}
          initialError={
            error
              ? apiErrorMessage({ error, status }, tBundle("catalogLoadFailed"))
              : null
          }
          initialView={initialView}
          initialSections={sections}
        />
      </ContentBlock>
    </ExplorePendingProvider>
  );
}
