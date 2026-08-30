import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock";
import {
  CatalogGallerySkeleton,
  ExploreSortSelect,
  ExploreTypeTabs,
  ExploreViewToggle,
} from "../bundles/components/CatalogGallery";
import { EXPLORE_VIEW_COOKIE } from "../bundles/components/catalog-data";

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
  const cookieStore = await cookies();
  const initialView =
    cookieStore.get(EXPLORE_VIEW_COOKIE)?.value === "table" ? "table" : "grid";

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Explore" }],
        description:
          "Browse the catalog. Filter by type, use case, or integration, then add to your workspace.",
      }}
      subheader={
        <>
          <ExploreTypeTabs initialType="bundles" />
          <div className="flex items-center gap-2">
            <ExploreSortSelect />
            <ExploreViewToggle initialView={initialView} />
          </div>
        </>
      }
    >
      <CatalogGallerySkeleton initialView={initialView} />
    </ContentBlock>
  );
}
