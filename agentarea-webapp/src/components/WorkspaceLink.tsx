"use client";

import type { ComponentProps } from "react";
import Link from "next/link";
import { useWorkspaceSlug } from "@/hooks/useWorkspaceNavigation";
import { prefixWorkspaceHref } from "@/lib/workspace-routes";

/**
 * `next/link` that keeps in-app paths (`/agents/1`) inside the workspace of
 * the current page. Other targets (auth, API, external, already prefixed)
 * pass through untouched.
 */
export default function WorkspaceLink({
  href,
  ...props
}: ComponentProps<typeof Link>) {
  const slug = useWorkspaceSlug();
  const scoped =
    typeof href === "string"
      ? prefixWorkspaceHref(href, slug)
      : typeof href.pathname === "string"
        ? { ...href, pathname: prefixWorkspaceHref(href.pathname, slug) }
        : href;
  return <Link href={scoped} {...props} />;
}
