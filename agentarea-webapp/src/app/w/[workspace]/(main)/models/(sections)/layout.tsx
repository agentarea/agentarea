import { Suspense } from "react";
import { getTranslations } from "next-intl/server";
import { cookies } from "next/headers";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import SearchInput from "@/components/SearchInput";
import { listProviderSpecsWithModels } from "@/lib/api";
import AddProviderButton from "../components/AddProviderButton";
import ModelsSectionTabs from "../components/ModelsSectionTabs";
import ProviderHeaderTabs from "../components/ProviderHeaderTabs";
import { MODELS_VIEW_COOKIE, resolveViewMode } from "../components/viewMode";

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
        <>
          <Suspense fallback={<ModelsSectionTabs />}>
            <CountedSectionTabs />
          </Suspense>
          <div className="flex flex-1 items-center justify-end gap-3">
            <SearchInput urlParamName="search" />
            <ProviderHeaderTabs initialView={initialView} />
          </div>
        </>
      }
    >
      {children}
    </ContentBlock>
  );
}

// The catalog size on the Available tab, streamed in so a slow catalog never
// holds the header back. A failed lookup just hides the number.
async function CountedSectionTabs() {
  const { data } = await listProviderSpecsWithModels();
  return <ModelsSectionTabs availableCount={data?.length} />;
}
