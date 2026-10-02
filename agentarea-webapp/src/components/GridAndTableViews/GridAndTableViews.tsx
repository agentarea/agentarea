import React from "react";
import { useTranslations } from "next-intl";
import Link from "@/components/WorkspaceLink";
import HeaderTabs from "@/components/HeaderTabs";
import Table from "@/components/Table/Table";
import { TabsContent } from "@/components/ui/tabs";
import { cn } from "@/lib/utils";
import { TabsWithNavigation } from "./components/TabsWithNavigation";

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

const TabsView = ({
  searchParams,
  selectedTab,
  showViewToggle = true,
  leftComponent,
  routeChange,
  children,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
  selectedTab?: string;
  showViewToggle?: boolean;
  leftComponent?: React.ReactNode;
  routeChange: string;
  children: React.ReactNode;
}) => {
  const t = useTranslations("Common");

  const tab = selectedTab ?? searchParams?.tab;
  const activeTab =
    typeof tab === "string" && (tab === "grid" || tab === "table")
      ? tab
      : "grid";

  return (
    <TabsWithNavigation activeTab={activeTab} routeChange={routeChange}>
      {(showViewToggle || leftComponent) && (
        <div className="mb-3 flex flex-row items-center justify-between gap-[10px]">
          <div className="flex flex-1 flex-row items-center gap-[10px]">
            {leftComponent}
          </div>

          {showViewToggle && (
            <div>
              <HeaderTabs
                paramName="tab"
                defaultTab="grid"
                currentTab={activeTab}
                tabs={[
                  { value: "table", label: t("table") },
                  { value: "grid", label: t("grid") },
                ]}
              />
            </div>
          )}
        </div>
      )}

      {children}
    </TabsWithNavigation>
  );
};

export default function GridAndTableViews<T extends GridItem>({
  searchParams,
  emptyState,
  leftComponent,
  routeChange,
  data,
  columns,
  cardContent,
  itemLink,
  rowHref,
  cardClassName,
  gridClassName,
  tableClassName,
  rowProps,
  selectedTab,
  showViewToggle = true,
  wrapCardContent = true,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
  isEmpty?: boolean;
  /** Required: a generic "no data" card teaches the user nothing. */
  emptyState: React.ReactNode;
  leftComponent?: React.ReactNode;
  routeChange: string;
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
  /** Use a route's existing view switcher instead of rendering a second one. */
  selectedTab?: string;
  showViewToggle?: boolean;
  /** `cardContent` owns its card and link, so do not add a shared wrapper. */
  wrapCardContent?: boolean;
}) {
  return (
    <TabsView
      routeChange={routeChange}
      searchParams={searchParams}
      selectedTab={selectedTab}
      showViewToggle={showViewToggle}
      leftComponent={leftComponent}
    >
      {!data.length ? (
        emptyState
      ) : (
        <>
          <TabsContent value="grid">
            <div
              className={cn(
                "grid grid-cols-1 gap-[12px] md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5",
                gridClassName
              )}
            >
              {data.map((item) => {
                const linkFunction = item.itemLink || itemLink;
                const { className: extraClassName, ...extraProps } =
                  rowProps?.(item) ?? {};
                if (!wrapCardContent) {
                  return (
                    <React.Fragment key={item.id}>
                      {cardContent(item)}
                    </React.Fragment>
                  );
                }
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
          </TabsContent>
          <TabsContent value="table">
            <Table
              data={data}
              className={tableClassName}
              columns={columns}
              rowProps={rowProps}
              // The row goes where the card goes. Passed as a href rather than
              // a click handler: this component renders on the server, so a
              // closure never reaches the browser and the rows were inert.
              rowHref={(item) =>
                rowHref?.(item) ?? (item.itemLink ?? itemLink)?.(item) ?? ""
              }
            />
          </TabsContent>
        </>
      )}
    </TabsView>
  );
}

export function GridAndTableSectionsViews<T extends GridItem>({
  searchParams,
  emptyState,
  leftComponent,
  routeChange,
  data,
  columns,
  cardContent,
  itemLink,
  cardClassName,
  gridClassName,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
  isEmpty?: boolean;
  /** Required: a generic "no data" card teaches the user nothing. */
  emptyState: React.ReactNode;
  leftComponent?: React.ReactNode;
  routeChange: string;
  data: {
    sectionId: string;
    sectioName?: string;
    cardClassName?: string;
    data: T[];
    /** Required: what this section holds and how it gets filled. */
    emptyState: React.ReactNode;
    itemLink?: (item: T) => string;
  }[];
  columns: Column<T>[];
  cardContent: (item: T) => React.ReactNode;
  itemLink?: (item: T) => string;
  cardClassName?: string;
  gridClassName?: string;
}) {
  return (
    <TabsView
      routeChange={routeChange}
      searchParams={searchParams}
      leftComponent={leftComponent}
    >
      {!data.length ? (
        emptyState
      ) : (
        <>
          {data.map((sectionData, key) => (
            <React.Fragment key={`tabs-section-${key}`}>
              {sectionData.sectioName && (
                <div className="my-5 flex flex-row items-center gap-[10px]">
                  <h2 className="whitespace-nowrap text-lg font-medium text-zinc-400">
                    {sectionData.sectioName}
                  </h2>
                  <div className="h-[1px] w-full bg-zinc-200 dark:bg-zinc-600" />
                </div>
              )}
              {sectionData.data.length > 0 ? (
                <>
                  <TabsContent value="grid">
                    <div
                      className={cn(
                        "grid grid-cols-1 gap-[12px] md:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5",
                        gridClassName
                      )}
                    >
                      {sectionData.data.map((item) => {
                        const linkFunction = sectionData.itemLink || itemLink;
                        return linkFunction ? (
                          <Link
                            key={item.id}
                            href={linkFunction(item)}
                            className={cn(
                              "card card-shadow group",
                              cardClassName,
                              sectionData.cardClassName
                            )}
                          >
                            {cardContent(item)}
                          </Link>
                        ) : (
                          <div
                            key={item.id}
                            className={cn(
                              "card card-shadow group",
                              cardClassName,
                              sectionData.cardClassName
                            )}
                          >
                            {cardContent(item)}
                          </div>
                        );
                      })}
                    </div>
                  </TabsContent>
                  <TabsContent value="table">
                    {(() => {
                      const linkFn = sectionData.itemLink || itemLink;
                      return (
                        <Table
                          data={sectionData.data}
                          columns={columns}
                          rowHref={(item) => linkFn?.(item) ?? ""}
                        />
                      );
                    })()}
                  </TabsContent>
                </>
              ) : (
                sectionData.emptyState
              )}
            </React.Fragment>
          ))}
        </>
      )}
    </TabsView>
  );
}
