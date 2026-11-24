import type { ReactNode } from "react";
import { ToolbarDivider } from "@/components/ui/toolbar";
import { cn } from "@/lib/utils";

export interface SubheaderToolbarProps {
  /** Category tabs — a `CountSegmentedControl`. */
  categories?: ReactNode;
  /** A `SearchInput`. */
  search?: ReactNode;
  /** Right side: `DisplayMenu`, `HeaderTabs`, any other control. */
  controls?: ReactNode;
  /** Class for the search slot and its divider, e.g. to move it out on a phone. */
  searchClassName?: string;
}

/**
 * The layout of a list page's ContentBlock subheader, in its fixed order:
 * categories, a divider, search, then the controls on the right.
 *
 * On a narrow screen the categories give way first and scroll sideways (the
 * segmented control scrolls itself); the search keeps a usable width and the
 * controls never shrink, so every control stays on screen.
 */
export default function SubheaderToolbar({
  categories,
  search,
  controls,
  searchClassName,
}: SubheaderToolbarProps) {
  return (
    <div className="flex h-full min-w-0 flex-1 items-center gap-1.5">
      {categories && (
        <div className="flex min-w-0 items-center">{categories}</div>
      )}
      {categories && search && <ToolbarDivider className={searchClassName} />}
      <div className="flex flex-1 items-center justify-end gap-3">
        {search && (
          <div className={cn("min-w-[7rem] flex-1", searchClassName)}>
            {search}
          </div>
        )}
        {controls && (
          <div className="flex shrink-0 items-center gap-3">{controls}</div>
        )}
      </div>
    </div>
  );
}
