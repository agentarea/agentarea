import { redirect } from "next/navigation";
import { getPersonalWorkspacePath } from "@/lib/workspace-context";

/**
 * `/bundles/import?src=<url>` is the link the landing page's "Install" button
 * sends, and it cannot know the workspace. It opens in the personal one; a
 * member of several picks another on that page (InstallTarget).
 */
export default async function ImportBundleLink({
  searchParams,
}: {
  searchParams: Promise<{ src?: string | string[] }>;
}) {
  const { src } = await searchParams;
  const link = Array.isArray(src) ? src[0] : src;
  const query = link ? `?src=${encodeURIComponent(link)}` : "";
  redirect(await getPersonalWorkspacePath(`/bundles/import${query}`));
}
