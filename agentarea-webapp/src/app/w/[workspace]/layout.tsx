import { notFound } from "next/navigation";
import { ViewerCapabilitiesProvider } from "@/components/ViewerCapabilities";
import { CurrencyProvider } from "@/hooks/useCurrency";
import { getPricingCurrency } from "@/lib/api-dashboard";
import { getViewerCapabilities, getWorkspaces } from "@/lib/workspace-context";

/**
 * The URL names the workspace. A slug the caller is not a member of is a
 * missing page, never a silent switch to another workspace.
 */
export default async function WorkspaceLayout({
  children,
  params,
}: {
  children: React.ReactNode;
  params: Promise<{ workspace: string }>;
}) {
  const [{ workspace }, workspaces] = await Promise.all([
    params,
    getWorkspaces(),
  ]);
  if (!workspaces.some((candidate) => candidate.slug === workspace)) {
    notFound();
  }
  const [capabilities, pricingCurrency] = await Promise.all([
    getViewerCapabilities(),
    getPricingCurrency(),
  ]);
  return (
    <ViewerCapabilitiesProvider capabilities={capabilities}>
      <CurrencyProvider
        currency={pricingCurrency.ok ? pricingCurrency.currency : null}
      >
        {children}
      </CurrencyProvider>
    </ViewerCapabilitiesProvider>
  );
}
