"use client";

import { useMemo } from "react";
import { useParams, usePathname, useRouter } from "next/navigation";
import {
  prefixWorkspaceHref,
  stripWorkspacePrefix,
  workspacePath,
} from "@/lib/workspace-routes";

/** The slug of the `/w/{slug}` page this renders on, or null off one. */
export function useWorkspaceSlug(): string | null {
  const params = useParams<{ workspace?: string }>();
  return params?.workspace ?? null;
}

/** Build a link to `path` inside the current workspace. */
export function useWorkspacePath(): (path: string) => string {
  const slug = useWorkspaceSlug();
  return useMemo(
    () => (path: string) => (slug ? workspacePath(slug, path) : path),
    [slug]
  );
}

/** The router, with in-app paths (`/agents/1`) kept in the current workspace. */
export function useWorkspaceRouter() {
  const router = useRouter();
  const slug = useWorkspaceSlug();
  return useMemo(
    () => ({
      ...router,
      push: (href: string, options?: Parameters<typeof router.push>[1]) =>
        router.push(prefixWorkspaceHref(href, slug), options),
      replace: (href: string, options?: Parameters<typeof router.replace>[1]) =>
        router.replace(prefixWorkspaceHref(href, slug), options),
      prefetch: (
        href: string,
        options?: Parameters<typeof router.prefetch>[1]
      ) => router.prefetch(prefixWorkspaceHref(href, slug), options),
    }),
    [router, slug]
  );
}

/** The pathname without its `/w/{slug}` prefix, as app code writes paths. */
export function useWorkspacePathname(): string {
  return stripWorkspacePrefix(usePathname());
}
