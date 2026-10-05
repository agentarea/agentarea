import React from "react";
import Link from "@/components/WorkspaceLink";
import Table from "@/components/Table/Table";
import { CARD_GRID_LOOSE } from "@/lib/collectionGrids";
import { cn } from "@/lib/utils";

type GridItem = {
  id: React.Key;
  itemLink?: (item: GridItem) => string;
};

type Column<T> = {
  header: string;
  accessor: string;
  render?(value: unknown, item?: T): React.ReactNode;
  headerClassName?: string;
  cellClassName?: string;
  /** Marks the identity cell as the row's native link when `rowHref` is set. */
  rowLink?: boolean;
};

/**
 * A list page's items as cards or as a table. The table / grid switch is not
 * here: it lives in the page subheader (`ViewModeTabs` in `SubheaderToolbar`),
 * and the page passes the chosen `viewMode` down.
 */
export default function GridAndTableViews<T extends GridItem>({
  viewMode = "grid",
  emptyState,
  data,
  columns,
  cardContent,
  itemLink,
  rowHref,
  cardClassName,
  gridClassName,
  tableClassName,
  rowProps,
  wrapCardContent = true,
}: {
  viewMode?: string;
  /** Required: a generic "no data" card teaches the user nothing. */
  emptyState: React.ReactNode;
  data: T[];
  columns: Column<T>[];
  cardContent: (item: T) => React.ReactNode;
  /** Link the shared card wrapper; table rows use `rowHref` when provided. */
  itemLink?: (item: T) => string;
  rowHref?: (item: T) => string;
  cardClassName?: string;
  gridClassName?: string;
  tableClassName?: string;
  /** Extra attributes for each row and wrapped card. */
  rowProps?: (item: T) => React.HTMLAttributes<HTMLElement>;
  /** `cardContent` owns its card and link, so do not add a shared wrapper. */
  wrapCardContent?: boolean;
}) {
  if (!data.length) return emptyState;

  if (viewMode === "table") {
    return (
      <Table
        data={data}
        className={tableClassName}
        columns={columns}
        rowProps={rowProps}
        // The row goes where the card goes. Passed as a href rather than a
        // click handler: this component renders on the server, so a closure
        // never reaches the browser and the rows were inert.
        rowHref={(item) =>
          rowHref?.(item) ?? (item.itemLink ?? itemLink)?.(item) ?? ""
        }
      />
    );
  }

  return (
    <div className={cn(CARD_GRID_LOOSE, gridClassName)}>
      {data.map((item) => {
        if (!wrapCardContent) {
          return (
            <React.Fragment key={item.id}>{cardContent(item)}</React.Fragment>
          );
        }
        const linkFunction = item.itemLink || itemLink;
        const { className: extraClassName, ...extraProps } =
          rowProps?.(item) ?? {};
        return linkFunction ? (
          <Link
            key={item.id}
            href={linkFunction(item)}
            {...extraProps}
            className={cn(
              "card card-shadow group",
              cardClassName,
              extraClassName
            )}
          >
            {cardContent(item)}
          </Link>
        ) : (
          <div
            key={item.id}
            {...extraProps}
            className={cn(
              "card card-shadow group",
              cardClassName,
              extraClassName
            )}
          >
            {cardContent(item)}
          </div>
        );
      })}
    </div>
  );
}
