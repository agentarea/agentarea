import { getTranslations } from "next-intl/server";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { WorkplaceSkeleton } from "./components/WorkplaceSkeleton";

// Shown on navigation until page.tsx renders. The page then keeps the same
// header and swaps in the same skeleton as its Suspense fallback, so the two
// hand over without a flash.
export default async function WorkplaceLoading() {
  const tPage = await getTranslations("WorkplacePage");

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: tPage("workplace"), href: "/workplace" }],
      }}
      className="p-0"
    >
      <WorkplaceSkeleton />
    </ContentBlock>
  );
}
