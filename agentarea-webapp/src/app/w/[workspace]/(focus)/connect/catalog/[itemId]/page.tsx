import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { notFound, redirect } from "next/navigation";
import { CatalogKeyConnect } from "@/app/w/[workspace]/(main)/connections/components/CatalogKeyConnect";
import { CredentialEncryptionNote } from "@/app/w/[workspace]/(main)/connections/components/CredentialFields";
import { OAuthConnectPanel } from "@/app/w/[workspace]/(main)/connections/OAuthConnectPanel";
import { FocusCard, FocusHeader, FocusStep } from "@/components/FocusCard";
import FormError from "@/components/FormError";
import { Button } from "@/components/ui/button";
import Link from "@/components/WorkspaceLink";
import { getCatalogConnectForm, getCatalogItem } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import {
  catalogServerSetupHref,
  existingConnectionsHref,
  isCatalogApi,
} from "@/lib/catalog-connections";
import { firstIconSrc, openApiIdentity } from "@/lib/entity-identity";
import { getWorkspaces } from "@/lib/workspace-context";
import { workspacePath } from "@/lib/workspace-routes";

interface Props {
  params: Promise<{ workspace: string; itemId: string }>;
  searchParams: Promise<{ another?: string | string[] }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { itemId } = await params;
  const t = await getTranslations("MCPServersPage.connectLink");
  const item = (await getCatalogItem(itemId)).data;
  return { title: t("metaTitle", { name: item?.name ?? "" }) };
}

/**
 * Where a connect link for a catalog API lands: the connection does not exist
 * until the person signs in, so the page starts that sign-in and nothing else.
 * When the workspace already holds one, it says so first: signing in again
 * makes a second connection, which is a choice, not the default.
 */
export default async function CatalogConnectLinkPage({
  params,
  searchParams,
}: Props) {
  const { workspace, itemId } = await params;
  const { another } = await searchParams;
  const t = await getTranslations("MCPServersPage");

  const [itemResult, formResult, workspaces] = await Promise.all([
    getCatalogItem(itemId),
    getCatalogConnectForm(itemId),
    getWorkspaces(),
  ]);
  const form = formResult.data;
  const current = workspaces.find((candidate) => candidate.slug === workspace);
  if (!current) notFound();

  const item = itemResult.data;
  if (!item) {
    return (
      <FocusCard>
        <FormError>
          {apiErrorMessage(itemResult, t("catalogConnect.loadFailed"))}
        </FormError>
      </FocusCard>
    );
  }
  if (!isCatalogApi(item.spec)) {
    redirect(workspacePath(workspace, catalogServerSetupHref(itemId)));
  }

  const spec = (item.spec ?? {}) as {
    base_url?: string;
    raw_spec?: Record<string, unknown>;
  };
  const identity = openApiIdentity({
    base_url: spec.base_url,
    name: item.name,
  });
  const icon = firstIconSrc(spec.raw_spec);
  if (icon) identity.sources = [icon, ...identity.sources];
  const existing = item.workspace_connections ?? [];
  const openHref = existingConnectionsHref(itemId, existing);

  return (
    <FocusCard>
      <FocusHeader
        identity={identity}
        title={t("connectLink.title", { provider: item.name })}
        subtitle={t("connectLink.workspace", { workspace: current.name })}
      />
      {openHref && another !== "1" ? (
        <FocusStep
          kind="done"
          title={t("connectLink.alreadyTitle", {
            name: existing[0].name,
            others: existing.length - 1,
          })}
          detail={t("connectLink.alreadyDetail", {
            others: existing.length - 1,
          })}
        >
          <Button asChild size="lg" className="w-full">
            <Link href={openHref}>{t("connectLink.open")}</Link>
          </Button>
          <Button asChild size="lg" variant="outline" className="w-full">
            <Link href={`/connect/catalog/${itemId}?another=1`}>
              {t("connectLink.connectAnother")}
            </Link>
          </Button>
        </FocusStep>
      ) : form?.auth === "api_key" ? (
        <CatalogKeyConnect
          itemId={itemId}
          provider={item.name}
          fields={form.fields ?? []}
          returnPath={`/connect/catalog/${itemId}`}
        />
      ) : (
        <div className="space-y-4">
          <OAuthConnectPanel
            target={{ kind: "catalog", itemId }}
            isUrlType
            bare
            returnPath={workspacePath(workspace, `/connect/catalog/${itemId}`)}
            title={t("connectLink.signInTitle", { provider: item.name })}
            actionLabel={t("connectLink.signInButton", {
              provider: item.name,
            })}
          />
        </div>
      )}
      <CredentialEncryptionNote className="mt-auto border-t border-border pt-4" />
    </FocusCard>
  );
}
