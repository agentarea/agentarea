import { redirect } from "next/navigation";
import { deepLinkPath } from "@/lib/deep-link";
import { getPersonalWorkspacePath } from "@/lib/workspace-context";

/**
 * Where the landing's bundle link (`/bundles/import?src=<url>`) sends someone.
 * The landing cannot know their workspace, so this lands them in the personal
 * one, where the import wizard fetches and analyzes the bundle.
 */
export default async function BundleImportPage({
  searchParams,
}: {
  searchParams: Promise<{ src?: string | string[] }>;
}) {
  const { src } = await searchParams;
  redirect(
    await getPersonalWorkspacePath(deepLinkPath("/bundles/import", "src", src))
  );
}
