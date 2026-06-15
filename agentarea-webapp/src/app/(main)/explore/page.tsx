import type { Metadata } from "next";
import ContentBlock from "@/components/ContentBlock";
import CatalogGallery from "../bundles/components/CatalogGallery";

export const metadata: Metadata = {
  title: "Explore",
};

// Unified discovery surface: one faceted gallery across every catalog type
// (bundles, agents, skills, connections). This is the maker-facing "Explore"
// destination — browse, filter, and add into the workspace.
export default function ExplorePage() {
  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: "Explore" }],
        description:
          "Browse the catalog. Filter by type, use case, or integration, then add to your workspace.",
      }}
    >
      <CatalogGallery />
    </ContentBlock>
  );
}
