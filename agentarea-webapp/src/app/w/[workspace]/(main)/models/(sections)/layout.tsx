import { Suspense } from "react";
import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import SearchInput from "@/components/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { listProviderConfigs, listProviderSpecsWithModels } from "@/lib/api";
import AddProviderButton from "../components/AddProviderButton";
import ModelsSectionTabs from "../components/ModelsSectionTabs";
import ProviderHeaderTabs from "../components/ProviderHeaderTabs";
import { MODELS_VIEW_COOKIE, resolveViewMode } from "../components/viewMode";

// One browser-tab title for both tabs, the same one the header shows.
export async function generateMetadata(): Promise<Metadata> {
  const t = await getTranslations("Models");
  return { title: t("title") };
}

/**
 * Chrome shared by the Connected and Available tabs. It lives in a layout so
 * switching tabs keeps the header, the section switch, search and the view
 * toggle mounted; only the content below swaps, behind its own skeleton.
 */
export default async function ModelsSectionsLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const [t, cookieStore] = await Promise.all([
    getTranslations("Models"),
    cookies(),
  ]);
  const initialView = resolveViewMode(
    undefined,
    cookieStore.get(MODELS_VIEW_COOKIE)?.value
  );

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title"), href: "/models" }],
        description: t("description"),
        controls: <AddProviderButton />,
      }}
      subheader={
        <SubheaderToolbar
          categories={
            <Suspense fallback={<ModelsSectionTabs />}>
              <CountedSectionTabs />
            </Suspense>
          }
          search={<SearchInput urlParamName="search" />}
          controls={<ProviderHeaderTabs initialView={initialView} />}
        />
      }
    >
      {children}
    </ContentBlock>
  );
}

// How many configs are connected and how big the catalog is, streamed in so
// a slow lookup never holds the header back. A failed one just hides its
// number. Connected counts platform-supplied configs too: that tab lists them.
async function CountedSectionTabs() {
  const [configs, specs] = await Promise.all([
    listProviderConfigs(),
    listProviderSpecsWithModels(),
  ]);
  return (
    <ModelsSectionTabs
      counts={{
        connected: configs.data?.length,
        available: specs.data?.length,
      }}
    />
  );
}
