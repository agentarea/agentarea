"use client";

import React, { useCallback, useMemo } from "react";
import { Input } from "@/components/ui/input";
import { Search } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import EmptyState from "@/components/EmptyState/EmptyState";
import GridAndTableViews from "@/components/GridAndTableViews";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Agent } from "@/types";
import AgentCard from "./AgentCard";
import { useSearchWithDebounce, useTabState } from "@/hooks";
import { AvatarCircles } from "@/components/ui/avatar-circles";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import { getToolAvatarUrls } from "@/utils/toolsDisplay";
import ModelBadge from "@/components/ui/model-badge";

export default function AgentsList({ initialAgents }: { initialAgents: Agent[] }) {
  const t = useTranslations("Agent");
  const commonT = useTranslations("Common");
  const router = useRouter();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  const [loading] = React.useState(false);

  const urlTab = searchParams.get("tab");
  const initialSearchQuery = searchParams.get("search") || "";

  const {
    query: searchQuery,
    debouncedQuery,
    isSearching,
    updateQuery,
    forceUpdate,
  } = useSearchWithDebounce(initialSearchQuery);

  const { currentTab, isTabLoaded, updateTab } = useTabState(pathname, urlTab);

  React.useEffect(() => {
    const params = new URLSearchParams(searchParams.toString());

    if (debouncedQuery.trim()) {
      params.set("search", debouncedQuery);
    } else {
      params.delete("search");
    }

    if (urlTab) {
      params.set("tab", urlTab);
    }

    const newUrl = params.toString() ? `?${params.toString()}` : "";
    router.replace(`/agents${newUrl}`, { scroll: false });
  }, [debouncedQuery, router, searchParams, urlTab]);

  React.useEffect(() => {
    if (urlTab) {
      updateTab(urlTab);
    }
  }, [urlTab, updateTab]);

  const handleSearchChange = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      updateQuery(e.target.value);
    },
    [updateQuery]
  );

  const handleKeyDown = useCallback(
    (e: React.KeyboardEvent<HTMLInputElement>) => {
      if (e.key === "Enter") {
        forceUpdate();
      }
    },
    [forceUpdate]
  );

  const columns = [
    {
      header: t("name"),
      render: (value: string) => <div className="font-semibold truncate">{value}</div>,
      accessor: "name",
    },
    {
      header: t("model"),
      accessor: "model_id",
      render: (_value: string, item: any) => (
        <ModelBadge 
          modelId={item.model_id} 
          providerName={item.model_info?.provider_name}
          modelDisplayName={item.model_info?.model_display_name}
          configName={item.model_info?.config_name}
          className="max-w-max" 
        />
      ),
    },
    {
      header: t("description"),
      accessor: "description",
      render: (value: string) => (
        <div className="max-w-xs truncate note" title={value}>
          {value}
        </div>
      ),
    },
    {
      header: t("tools"),
      accessor: "tools",
      render: (_value: string, item: Agent) => {
        const toolAvatars = getToolAvatarUrls(item);
        return toolAvatars.length > 0 ? (
          <AvatarCircles maxDisplay={5} avatarUrls={toolAvatars} />
        ) : (
          <span className="text-xs text-muted-foreground">{t("noTools")}</span>
        );
      },
    },
    {
      header: "",
      accessor: "id",
      render: (_value: string, item: any) => (
        <div className="flex gap-2">
          <Link href={`/agents/${item.id}`} onClick={(e) => e.stopPropagation()}>
            <Button variant="ghost" size="sm" className="gap-1 text-muted-foreground hover:text-foreground">
            Explore
            </Button>
          </Link>
        </div>
      ),
    },
  ];

  const filterData = useCallback(
    (data: any[]) => {
      if (!debouncedQuery.trim()) return data;

      const query = debouncedQuery.toLowerCase();
      return data.filter((item) => {
        return (
          item.name?.toLowerCase().includes(query) ||
          item.description?.toLowerCase().includes(query) ||
          item.model_id?.toLowerCase().includes(query) ||
          item.status?.toLowerCase().includes(query)
        );
      });
    },
    [debouncedQuery]
  );

  const filteredAgents = useMemo(() => filterData(initialAgents), [filterData, initialAgents]);

  return (
    <>
      {loading || (!isTabLoaded && !urlTab) ? (
        <div className="flex items-center justify-center h-32">
          <LoadingSpinner />
        </div>
      ) : (
        <GridAndTableViews
          isEmpty={filteredAgents.length === 0}
          emptyState={
            <EmptyState
              iconsType="agent"
              title={t("noAgentsYet")}
              description={t("getStartedByAddingYourFirstAgent")}
              action={{ label: t("addYourFirstAgent"), href: "/agents/create" }}
            />
          }
          searchParams={{
            ...Object.fromEntries(searchParams.entries()),
            tab: currentTab,
          }}
          data={filteredAgents}
          columns={columns}
          routeChange="/agents"
          cardContent={(item) => <AgentCard agent={item} />}
          cardClassName="px-0 pb-0 overflow-hidden"
          itemLink={(agent) => `/agents/${agent.id}`}
          gridClassName="grid-cols-1 sm:grid-cols-2 md:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4"
          leftComponent={
            <div className="relative w-full focus-within:w-full max-w-full transition-all duration-300">
              <div className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground">
                {isSearching ? <LoadingSpinner size="sm" text="" /> : <Search className="h-4 w-4" />}
              </div>
              <Input
                placeholder={commonT("search")}
                className="pl-9 w-full"
                value={searchQuery}
                onChange={handleSearchChange}
                onKeyDown={handleKeyDown}
              />
            </div>
          }
        />
      )}
    </>
  );
}


