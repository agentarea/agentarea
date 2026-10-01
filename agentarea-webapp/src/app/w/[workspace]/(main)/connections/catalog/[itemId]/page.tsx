import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { preflightCatalogConnection } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { OAuthConnectPanel } from "../../OAuthConnectPanel";

export const metadata: Metadata = {
  title: "Connect",
};

export default async function CatalogConnectPage({
  params,
}: {
  params: Promise<{ itemId: string }>;
}) {
  const { itemId } = await params;
  const t = await getTranslations("MCPServersPage");

  const result = await preflightCatalogConnection(itemId);
  const item = result.data;

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/connections" },
          {
            label: item
              ? t("catalogConnect.breadcrumbWithName", { name: item.name })
              : t("catalogConnect.breadcrumb"),
          },
        ],
        description: item?.description ?? undefined,
        backLink: {
          label: t("catalogConnect.back"),
          href: `/explore?type=connections&item=${encodeURIComponent(itemId)}`,
        },
      }}
    >
      {!item ? (
        <div className="py-6">
          <div className="rounded-lg border border-destructive/20 bg-destructive/5 p-4 text-sm text-destructive">
            {apiErrorMessage(result, t("catalogConnect.loadFailed"))} (id:{" "}
            {itemId})
          </div>
        </div>
      ) : (
        <div className="mx-auto w-full max-w-[600px] px-2 py-10">
          <OAuthConnectPanel target={{ kind: "catalog", itemId }} isUrlType />
        </div>
      )}
    </ContentBlock>
  );
}
