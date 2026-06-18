import type { Metadata } from "next";
import ContentBlock from "@/components/ContentBlock";
import ImportWizard from "../components/ImportWizard";

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

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: "Bundles", href: "/bundles" },
          { label: "Import" },
        ],
        description: "Install a pre-built agent package into your workspace.",
      }}
    >
      <ImportWizard initialSrc={initialSrc} />
    </ContentBlock>
  );
}
