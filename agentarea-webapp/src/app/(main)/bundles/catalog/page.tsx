import type { Metadata } from "next";
import ContentBlock from "@/components/ContentBlock";
import { browseCatalog } from "@/lib/api";
import CatalogGallery from "../components/CatalogGallery";
import {
  PAGE,
  isCatalogType,
  normalize,
  type CatalogEntry,
  type CatalogType,
  type RegistryItem,
} from "../components/catalog-data";

export const metadata: Metadata = {
  title: "Bundle Catalog",
};

interface BundleCatalogPageProps {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}

// Experimental, isolated prototype of a faceted bundle gallery. Reachable
// directly at /bundles/catalog — intentionally not wired into navigation so it
// sits alongside the existing import flow without changing it. The first page is
// server-rendered (same SSR path as /explore).
export default async function BundleCatalogPage({
  searchParams,
}: BundleCatalogPageProps) {
  const sp = await searchParams;
  const type: CatalogType = isCatalogType(sp.type) ? sp.type : "bundles";

  const { items, total, categories, error } = await browseCatalog({
    registryType: type,
    limit: PAGE,
    offset: 0,
  });
  const entries: CatalogEntry[] = (items as RegistryItem[]).map((it) =>
    normalize(type, it)
  );

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
      <CatalogGallery
        key={type}
        initialType={type}
        initialEntries={entries}
        initialTotal={total}
        initialCategories={categories}
        initialError={error ? "Failed to load catalog." : null}
      />
    </ContentBlock>
  );
}
