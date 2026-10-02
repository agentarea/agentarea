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
  cardClassName,
  gridClassName,
  rowProps,
}: {
  viewMode?: string;
  /** Required: a generic "no data" card teaches the user nothing. */
  emptyState: React.ReactNode;
  data: T[];
  columns: Column<T>[];
  cardContent: (item: T) => React.ReactNode;
  itemLink?: (item: T) => string;
  cardClassName?: string;
  gridClassName?: string;
  /** Extra attributes for each row and card, e.g. drag source or drop target. */
  rowProps?: (item: T) => React.HTMLAttributes<HTMLElement>;
}) {
  if (!data.length) return emptyState;

  if (viewMode === "table") {
    return (
      <Table
        data={data}
        columns={columns}
        rowProps={rowProps}
        // The row goes where the card goes. Passed as a href rather than a
        // click handler: this component renders on the server, so a closure
        // never reaches the browser and the rows were inert.
        rowHref={(item) => (item.itemLink ?? itemLink)?.(item) ?? ""}
      />
    );
  }

  return (
    <div className={cn(CARD_GRID_LOOSE, gridClassName)}>
      {data.map((item) => {
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
