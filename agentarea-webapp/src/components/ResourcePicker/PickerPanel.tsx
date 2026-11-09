"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";
import { ArrowUpRight } from "lucide-react";
import SearchInput from "@/components/SearchInput/SearchInput";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import {
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import Link from "@/components/WorkspaceLink";

/**
 * The frame of a pick-from-a-list sheet, as the task's attach sheet draws it:
 * a ruled header, the subheader's 42px band under it (tabs, a divider, the
 * search — as on a list page), the list scrolling below, and a footer with the way to
 * manage what is listed. Goes in a `ConfigSheet` with `panel`, which leaves
 * the header and padding to this.
 */
export function PickerPanel({
  title,
  description,
  onSearch,
  tabs,
  manageText,
  manageHref,
  footerNote,
  footer,
  children,
}: {
  title: ReactNode;
  description: ReactNode;
  /** Left out where there is nothing to search, e.g. on a form tab. */
  onSearch?: (query: string) => void;
  /** A CountSegmentedControl when the sheet holds more than one list. */
  tabs?: ReactNode;
  manageText?: string;
  manageHref?: string;
  /** Right side of the footer, e.g. that changes apply instantly. */
  footerNote?: ReactNode;
  /** The whole footer in place of the link, e.g. a form's actions. */
  footer?: ReactNode;
  children: ReactNode;
}) {
  const tCommon = useTranslations("Common");

  const search = onSearch && (
    <SearchInput
      delay={150}
      onDebouncedChange={onSearch}
      placeholder={tCommon("search")}
    />
  );

  return (
    <>
      <SheetHeader className="space-y-1 border-b px-5 pb-4 pr-12 pt-5 text-left">
        <SheetTitle className="text-[15px]">{title}</SheetTitle>
        <SheetDescription className="text-xs">{description}</SheetDescription>
      </SheetHeader>

      {(tabs || search) && (
        // The subheader's 42px band: the search carries its own padding.
        <div className="flex h-[42px] shrink-0 items-center border-b px-5">
          <SubheaderToolbar categories={tabs} search={search} />
        </div>
      )}

      <div className="min-h-0 flex-1 overflow-y-auto py-2">{children}</div>

      {(footer || manageHref || footerNote) && (
        <div className="flex items-center justify-between gap-3 border-t px-5 py-3">
          {footer}
          {!footer && manageHref && (
            <Link
              href={manageHref}
              target="_blank"
              rel="noopener noreferrer"
              className="inline-flex items-center gap-1 text-xs text-primary hover:underline"
            >
              {manageText}
              <ArrowUpRight className="h-3 w-3" />
            </Link>
          )}
          {!footer && footerNote}
        </div>
      )}
    </>
  );
}
