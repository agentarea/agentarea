"use client";

import { useWorkspaceSlug } from "@/hooks/useWorkspaceNavigation";
import { useClientEnv } from "@/lib/use-client-env";

/** Where this deployment's billing page lives, or "" when it has none. */
export function useBillingUrl(): string {
  return useClientEnv("CLIENT_BILLING_URL");
}

/**
 * The billing page for the workspace this page belongs to
 * (`{billing}/{slug}`), or "" when billing is off or the page has no workspace.
 */
export function useWorkspaceBillingUrl(): string {
  const billingUrl = useBillingUrl();
  const slug = useWorkspaceSlug();
  if (!billingUrl || !slug) return "";
  return `${billingUrl.replace(/\/+$/, "")}/${encodeURIComponent(slug)}`;
}
