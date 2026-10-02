import type { ReactNode } from "react";

export interface SubheaderToolbarProps {
  /** Category tabs — a `CountSegmentedControl`. */
  categories?: ReactNode;
  /** A `SearchInput`. */
  search?: ReactNode;
  /** Right side: `DisplayMenu`, `HeaderTabs`, any other control. */
  controls?: ReactNode;
}

/**
 * The layout of a list page's ContentBlock subheader, in its fixed order:
 * categories, search, then the controls on the right.
 *
 * On a narrow screen the categories give way first and scroll sideways (the
 * segmented control scrolls itself); the search keeps a usable width and the
 * controls never shrink, so every control stays on screen.
 */
export default function SubheaderToolbar({
  categories,
  search,
  controls,
}: SubheaderToolbarProps) {
  return (
    <div className="flex h-full min-w-0 flex-1 items-center gap-3 md:gap-10">
      {categories && (
        <div className="flex min-w-0 items-center">{categories}</div>
      )}
      <div className="flex flex-1 items-center justify-end gap-3">
        {search && <div className="min-w-[7rem] flex-1">{search}</div>}
        {controls && (
          <div className="flex shrink-0 items-center gap-3">{controls}</div>
        )}
      </div>
    </div>
  );
}
