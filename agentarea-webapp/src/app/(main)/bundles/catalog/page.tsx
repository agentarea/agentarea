import type { Metadata } from "next";
import ContentBlock from "@/components/ContentBlock";
import CatalogGallery from "../components/CatalogGallery";

export const metadata: Metadata = {
  title: "Bundle Catalog",
};

// Experimental, isolated prototype of a faceted bundle gallery. Reachable
// directly at /bundles/catalog — intentionally not wired into navigation so it
// sits alongside the existing import flow without changing it.
export default function BundleCatalogPage() {
  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Bundles", href: "/bundles" },
          { label: "Catalog" },
        ],
        description: "Browse installable bundles. Filter by use case or integration.",
      }}
    >
      <CatalogGallery />
    </ContentBlock>
  );
}
