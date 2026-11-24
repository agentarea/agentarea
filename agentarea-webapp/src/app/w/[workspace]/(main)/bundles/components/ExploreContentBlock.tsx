"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { parseAsString, useQueryState } from "nuqs";
import ContentBlock from "@/components/ContentBlock";
import { useExplorePending } from "./explore-pending";

/**
 * The explore page frame. With an item open (?item=) the header reads
 * "Catalog › GitHub" and the Catalog crumb returns to the list, the way every
 * other detail page is headed; the list keeps its filters and scroll.
 */
export default function ExploreContentBlock({
  subheader,
  children,
}: {
  subheader: ReactNode;
  children: ReactNode;
}) {
  const t = useTranslations("CatalogPage");
  const [itemId, setItemId] = useQueryState(
    "item",
    parseAsString.withOptions({ history: "push" })
  );
  const title = useExplorePending()?.activeTitle;

  return (
    <ContentBlock
      header={
        itemId
          ? {
              breadcrumb: [
                { label: t("title"), onClick: () => void setItemId(null) },
                { label: title ?? t("loading") },
              ],
            }
          : // No description: ContentBlock does not print it in breadcrumb
            // mode, it only top-aligns the row, which made the title sit high
            // and jump when an item opened.
            { breadcrumb: [{ label: t("title") }] }
      }
      subheader={subheader}
    >
      {children}
    </ContentBlock>
  );
}
