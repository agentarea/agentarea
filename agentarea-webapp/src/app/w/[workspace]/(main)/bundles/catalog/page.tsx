import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock";
import { browseCatalog } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import {
  normalize,
  PAGE,
  REGISTRY_TYPE,
  toCatalogType,
  type CatalogEntry,
  type CatalogType,
  type RegistryItem,
} from "../components/catalog-data";
import CatalogGallery from "../components/CatalogGallery";

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
  const type: CatalogType = toCatalogType(sp.type) ?? "bundles";

  const { items, total, categories, protocols, error, status } =
    await browseCatalog({
      registryType: REGISTRY_TYPE[type],
      limit: PAGE,
      offset: 0,
    });
  const tBundle = await getTranslations("BundleInstall");
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
        description:
          "Browse installable bundles. Filter by use case or integration.",
      }}
    >
      <CatalogGallery
        key={type}
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
      />
    </ContentBlock>
  );
}
