import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { readUiPrefs } from "@/lib/ui-prefs-server";
import { EXPLORE_VIEW_KEY } from "../bundles/components/catalog-data";
import {
  CatalogGallerySkeleton,
  ExploreSortSelect,
  ExploreTypeTabs,
  ExploreViewToggle,
} from "../bundles/components/CatalogGallery";
import { ExploreSearch } from "../bundles/components/ExploreFilters";

// Route-level Suspense fallback for /explore. The page is an async Server
// Component that awaits the first catalog page, so without this the nearest
// loading boundary is the root full-screen spinner — a white flash on hard
// refresh. Here we render the identical chrome (breadcrumb + type tabs + view
// toggle) and a faceted skeleton body, so the page paints its real frame
// instantly and only the content area fills in. Matches the in-component `busy`
// skeleton the gallery shows on type switches.
export default async function Loading() {
  // Seed the skeleton from the persisted view so a hard refresh skeletons the
  // same layout (grid vs table) the page will paint.
  const [t, uiPrefs] = await Promise.all([
    getTranslations("CatalogPage"),
    readUiPrefs(),
  ]);
  const initialView =
    uiPrefs.views[EXPLORE_VIEW_KEY] === "table" ? "table" : "grid";

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
      }}
      subheader={
        // Same size container as the page, so the labels fold alike.
        <div className="explore-cq flex h-full min-w-0 flex-1 items-center">
          <SubheaderToolbar
            categories={<ExploreTypeTabs initialType="bundles" />}
            // On a phone the search moves to the strip under the subheader.
            search={<ExploreSearch initialType="bundles" />}
            searchClassName="max-sm:hidden"
            controls={
              <>
                <ExploreSortSelect />
                <ExploreViewToggle initialView={initialView} />
              </>
            }
          />
        </div>
      }
    >
      <CatalogGallerySkeleton initialView={initialView} />
    </ContentBlock>
  );
}
