import React from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import EmptyState from "@/components/EmptyState/EmptyState";
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
  sortable?: boolean;
  sortableDirection?: "asc" | "desc";
};

const TabsView = ({
  searchParams,
  leftComponent,
  routeChange,
  children,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
  emptyState?: React.ReactNode;
  leftComponent?: React.ReactNode;
  routeChange: string;
  children: React.ReactNode;
}) => {
  const t = useTranslations("Common");

  const tab = searchParams?.tab;
  const activeTab =
    typeof tab === "string" && (tab === "grid" || tab === "table")
      ? tab
      : "grid";

  return (
    <TabsWithNavigation activeTab={activeTab} routeChange={routeChange}>
      <div className="mb-3 flex flex-row items-center justify-between gap-[10px]">
        <div className="flex flex-1 flex-row items-center gap-[10px]">
          {leftComponent}
        </div>

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
      </div>

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
  cardClassName,
  gridClassName,
}: {
  searchParams: { [key: string]: string | string[] | undefined };
  isEmpty?: boolean;
  emptyState?: React.ReactNode;
  leftComponent?: React.ReactNode;
  routeChange: string;
  data: T[];
  columns: Column<T>[];
  cardContent: (item: T) => React.ReactNode;
  itemLink?: (item: T) => string;
  cardClassName?: string;
  gridClassName?: string;
}) {
  const t = useTranslations("Common");

  return (
    <TabsView
      routeChange={routeChange}
      searchParams={searchParams}
      leftComponent={leftComponent}
    >
      {!data.length ? (
        emptyState || (
          <EmptyState
            title={t("emptyState.title")}
            description={t("emptyState.description")}
            iconsType="agent"
          />
        )
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
                return linkFunction ? (
                  <Link
                    key={item.id}
                    href={linkFunction(item)}
                    className={cn("card card-shadow group", cardClassName)}
                  >
                    {cardContent(item)}
                  </Link>
                ) : (
                  <div
                    key={item.id}
                    className={cn("card card-shadow group", cardClassName)}
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
              columns={columns}
              onRowClick={
                itemLink
                  ? (item) => window.location.assign(itemLink(item))
                  : undefined
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
  emptyState?: React.ReactNode;
  leftComponent?: React.ReactNode;
  routeChange: string;
  data: {
    sectionId: string;
    sectioName?: string;
    cardClassName?: string;
    data: T[];
    emptyState?: React.ReactNode;
    itemLink?: (item: T) => string;
  }[];
  columns: Column<T>[];
  cardContent: (item: T) => React.ReactNode;
  itemLink?: (item: T) => string;
  cardClassName?: string;
  gridClassName?: string;
}) {
  const t = useTranslations("Common");

  return (
    <TabsView
      routeChange={routeChange}
      searchParams={searchParams}
      leftComponent={leftComponent}
    >
      {!data.length ? (
        emptyState || (
          <EmptyState
            title={t("emptyState.title")}
            description={t("emptyState.description")}
            iconsType="agent"
          />
        )
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
                          onRowClick={
                            linkFn
                              ? (item) => window.location.assign(linkFn(item))
                              : undefined
                          }
                        />
                      );
                    })()}
                  </TabsContent>
                </>
              ) : (
                sectionData.emptyState || (
                  <EmptyState
                    title={t("emptyState.title")}
                    description={t("emptyState.description")}
                    iconsType="agent"
                  />
                )
              )}
            </React.Fragment>
          ))}
        </>
      )}
    </TabsView>
  );
}
