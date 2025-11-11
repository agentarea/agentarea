import { getTranslations } from "next-intl/server";
import Link from "next/link";
import { PlusCircleIcon, SearchIcon } from "lucide-react";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import EmptyState from "@/components/EmptyState/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { listProviderSpecsWithModels } from "@/lib/api";

export default async function ProviderSpecsPage({
  searchParams,
}: {
  searchParams: Promise<{ [key: string]: string | string[] | undefined }>;
}) {
  const t = await getTranslations("Common");
  const tProviders = await getTranslations("ProvidersPage");

  // Fetch provider specs with models
  const providersResponse = await listProviderSpecsWithModels();
  const providerSpecs = providersResponse.data || [];

  const columns = [
    {
      header: tProviders("table.provider"),
      accessor: "name",
      render: (value: string, row: any) => (
        <div className="flex items-center gap-3">
          {row.icon_url && (
            <img
              src={row.icon_url}
              alt={`${value} icon`}
              className="h-6 w-6 rounded"
            />
          )}
          <div>
            <div className="text-[14px] font-semibold md:text-[16px]">
              {value}
            </div>
            <div className="text-xs text-muted-foreground">
              {row.provider_key}
            </div>
          </div>
        </div>
      ),
    },
    {
      header: tProviders("table.description"),
      accessor: "description",
      cellClassName: "text-[12px] md:text-[14px]",
      render: (value: string) => (
        <div className="line-clamp-3 md:line-clamp-none">
          {value || tProviders("table.noDescription")}
        </div>
      ),
    },
    {
      header: tProviders("table.type"),
      accessor: "provider_type",
      render: (value: string) => (
        <div className="rounded-full bg-blue-100 px-2 py-1 text-xs text-blue-800">
          {value}
        </div>
      ),
    },
    {
      header: tProviders("table.models"),
      accessor: "models",
      render: (models: any[]) => (
        <div className="text-xs text-muted-foreground">
          {models?.length || 0} {tProviders("table.modelsCount")}
        </div>
      ),
    },
    {
      header: tProviders("table.status"),
      accessor: "is_builtin",
      render: (value: boolean) => (
        <div
          className={`rounded-full px-2 py-1 text-xs ${
            value ? "bg-green-100 text-green-800" : "bg-gray-100 text-gray-800"
          }`}
        >
          {value ? tProviders("table.builtIn") : tProviders("table.custom")}
        </div>
      ),
    },
  ];

  return (
    <ContentBlock
      header={{
        title: tProviders("title"),
        description: tProviders("description"),
        controls: (
          <Link href="/admin/providers/create" passHref legacyBehavior>
            <Button
              className="shrink-0 gap-2 shadow-sm"
              data-test="new-provider-button"
            >
              <PlusCircleIcon className="mr-2 h-4 w-4" />
              {tProviders("addProvider")}
            </Button>
          </Link>
        ),
      }}
    >
      <GridAndTableViews
        searchParams={await searchParams}
        data={providerSpecs}
        columns={columns}
        emptyState={
          <EmptyState
            title={tProviders("noProviders")}
            description={tProviders("emptyDescription")}
            iconsType="llm"
            action={{
              label: tProviders("addProvider"),
              href: "/admin/providers/create",
            }}
          />
        }
        routeChange="/admin/providers"
        cardContent={(item: any) => (
          <div className="flex flex-col gap-2">
            <div className="mb-2 flex items-center gap-3">
              {item.icon_url && (
                <img
                  src={item.icon_url}
                  alt={`${item.name} icon`}
                  className="h-8 w-8 rounded"
                />
              )}
              <div>
                <div className="text-[16px] font-[500]">
                  {item.name}
                </div>
                <div className="text-xs text-muted-foreground">
                  {item.provider_key}
                </div>
              </div>
            </div>
            <div className="line-clamp-2 text-[14px] opacity-50">
              {item.description || tProviders("table.noDescription")}
            </div>
            <div className="flex gap-2 text-xs text-muted-foreground">
              <span>
                {tProviders("table.type")}: {item.provider_type}
              </span>
              <span>•</span>
              <span>
                {tProviders("table.models")}: {item.models?.length || 0}
              </span>
            </div>
            <div className="flex gap-2">
              <div
                className={`rounded-full px-2 py-1 text-xs ${
                  item.is_builtin
                    ? "bg-green-100 text-green-800"
                    : "bg-gray-100 text-gray-800"
                }`}
              >
                {item.is_builtin
                  ? tProviders("table.builtIn")
                  : tProviders("table.custom")}
              </div>
            </div>
          </div>
        )}
        leftComponent={
          <div className="relative w-full max-w-full transition-all duration-300 focus-within:w-full">
            <div className="absolute left-3 top-1/2 -translate-y-1/2 transform text-muted-foreground">
              <SearchIcon className="h-4 w-4" />
            </div>
            <Input placeholder={t("search")} className="w-full pl-9" />
          </div>
        }
      />
    </ContentBlock>
  );
}
