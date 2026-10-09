import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";
import { notFound } from "next/navigation";
import { CredentialEncryptionNote } from "@/app/w/[workspace]/(main)/connections/components/CredentialFields";
import { OAuthConnectPanel } from "@/app/w/[workspace]/(main)/connections/OAuthConnectPanel";
import { FocusCard, FocusHeader } from "@/components/FocusCard";
import FormError from "@/components/FormError";
import { getCatalogItem, preflightCatalogConnection } from "@/lib/api";
import { apiErrorMessage } from "@/lib/api-errors";
import { firstIconSrc, openApiIdentity } from "@/lib/entity-identity";
import { getWorkspaces } from "@/lib/workspace-context";
import { workspacePath } from "@/lib/workspace-routes";

interface Props {
  params: Promise<{ workspace: string; itemId: string }>;
}

export async function generateMetadata({ params }: Props): Promise<Metadata> {
  const { itemId } = await params;
  const t = await getTranslations("MCPServersPage.connectLink");
  const preflight = (await preflightCatalogConnection(itemId)).data;
  return { title: t("metaTitle", { name: preflight?.name ?? "" }) };
}

/**
 * Where a connect link for a catalog API lands: the connection does not exist
 * until the person signs in, so the page starts that sign-in and nothing else.
 */
export default async function CatalogConnectLinkPage({ params }: Props) {
  const { workspace, itemId } = await params;
  const t = await getTranslations("MCPServersPage");

  const [preflightResult, itemResult, workspaces] = await Promise.all([
    preflightCatalogConnection(itemId),
    getCatalogItem(itemId),
    getWorkspaces(),
  ]);
  const current = workspaces.find((candidate) => candidate.slug === workspace);
  if (!current) notFound();

  const preflight = preflightResult.data;
  if (!preflight) {
    return (
      <FocusCard>
        <FormError>
          {apiErrorMessage(preflightResult, t("catalogConnect.loadFailed"))}
        </FormError>
      </FocusCard>
    );
  }

  const spec = (itemResult.data?.spec ?? {}) as {
    base_url?: string;
    raw_spec?: Record<string, unknown>;
  };
  const identity = openApiIdentity({
    base_url: spec.base_url,
    name: preflight.name,
  });
  const icon = firstIconSrc(spec.raw_spec);
  if (icon) identity.sources = [icon, ...identity.sources];

  return (
    <FocusCard>
      <FocusHeader
        identity={identity}
        title={t("connectLink.title", { provider: preflight.name })}
        subtitle={t("connectLink.workspace", { workspace: current.name })}
      />
      <div className="space-y-4">
        <OAuthConnectPanel
          target={{ kind: "catalog", itemId }}
          isUrlType
          bare
          returnPath={workspacePath(workspace, `/connect/catalog/${itemId}`)}
          title={t("connectLink.signInTitle", { provider: preflight.name })}
          actionLabel={t("connectLink.signInButton", {
            provider: preflight.name,
          })}
        />
      </div>
      <CredentialEncryptionNote className="mt-auto border-t border-border pt-4" />
    </FocusCard>
  );
}
