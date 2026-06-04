import type { Metadata } from "next";
import ContentBlock from "@/components/ContentBlock";
import ImportWizard from "../components/ImportWizard";

export const metadata: Metadata = {
  title: "Import Agent Package",
};

export default function ImportBundlePage() {
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
      <ImportWizard />
    </ContentBlock>
  );
}
