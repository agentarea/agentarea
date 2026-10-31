import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { redirect } from "next/navigation";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { getCatalogConnectForm, getCatalogItem } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import {
  catalogServerSetupHref,
  isCatalogApi,
} from "@/lib/catalog-connections";
import { workspacePath } from "@/lib/workspace-routes";
import { CatalogKeyConnect } from "../../components/CatalogKeyConnect";
import { OAuthConnectPanel } from "../../OAuthConnectPanel";

export const metadata: Metadata = {
  title: "Connect",
};

export default async function CatalogConnectPage({
  params,
}: {
  params: Promise<{ workspace: string; itemId: string }>;
}) {
  const { workspace, itemId } = await params;
  const t = await getTranslations("MCPServersPage");

  const [result, formResult] = await Promise.all([
    getCatalogItem(itemId),
    getCatalogConnectForm(itemId),
  ]);
  const item = result.data;
  if (item && !isCatalogApi(item.spec)) {
    redirect(workspacePath(workspace, catalogServerSetupHref(itemId)));
  }
  const form = formResult.data;

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
          {form?.auth === "api_key" ? (
            <CatalogKeyConnect
              itemId={itemId}
              provider={item.name}
              fields={form.fields ?? []}
            />
          ) : (
            <OAuthConnectPanel target={{ kind: "catalog", itemId }} isUrlType />
          )}
        </div>
      )}
    </ContentBlock>
  );
}
