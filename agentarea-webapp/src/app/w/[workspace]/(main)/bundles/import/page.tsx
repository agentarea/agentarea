import type { Metadata } from "next";
import ContentBlock from "@/components/ContentBlock";
import {
  getRequestWorkspaceSlug,
  getWorkspaceContext,
} from "@/lib/workspace-context";
import ImportWizard from "../components/ImportWizard";
import { InstallTarget } from "../components/InstallTarget";

export const metadata: Metadata = {
  title: "Import Agent Package",
};

export default async function ImportBundlePage({
  searchParams,
}: {
  searchParams: Promise<{ src?: string | string[] }>;
}) {
  const { src } = await searchParams;
  const initialSrc = Array.isArray(src) ? src[0] : src;
  const slug = await getRequestWorkspaceSlug();
  // A linked bundle may belong in another of the caller's workspaces.
  const { workspaces, active } = initialSrc
    ? await getWorkspaceContext()
    : { workspaces: [], active: null };

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Catalog", href: "/explore" },
          { label: "Import" },
        ],
        description: "Install a pre-built agent package into your workspace.",
      }}
    >
      <div className="space-y-6">
        {initialSrc && active && workspaces.length > 1 && (
          <InstallTarget
            workspaces={workspaces}
            current={active.slug}
            src={initialSrc}
          />
        )}
        {/* Keyed by workspace, so moving the link to another one starts over
            on that workspace's models and rights. */}
        <ImportWizard
          key={`${slug}:${initialSrc ?? ""}`}
          initialSrc={initialSrc}
        />
      </div>
    </ContentBlock>
  );
}
