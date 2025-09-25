"use client";

import React, { useState, useEffect, useCallback, useMemo } from "react";
import { Input } from "@/components/ui/input";
import { Bot, Search } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/ui/button";
import { listAgents } from "@/lib/api";
import EmptyState from "@/components/EmptyState/EmptyState";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { useRouter, useSearchParams, usePathname } from "next/navigation";
import { useTranslations } from "next-intl";
import { Agent } from "@/types";
import AgentCard from "./components/AgentCard";
import GridAndTableViews from "@/components/GridAndTableViews";
import { StatusBadge } from "@/components/ui/status-badge";
import { useSearchWithDebounce, useTabState } from "@/hooks";
import { AvatarCircles } from "@/components/ui/avatar-circles";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import ModelDisplay from "@/app/agents/components/ModelDisplay";
import { getToolAvatarUrls } from "@/utils/toolsDisplay";

export default function AgentsBrowsePage() {
  const t = useTranslations("Agent");
  const commonT = useTranslations("Common");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const router = useRouter();
  const searchParams = useSearchParams();
  const pathname = usePathname();
  
  const urlTab = searchParams.get("tab");
  const initialSearchQuery = searchParams.get("search") || "";
  
  // Используем кастомные хуки
  const {
    query: searchQuery,
    debouncedQuery,
    isSearching,
    updateQuery,
    forceUpdate
  } = useSearchWithDebounce(initialSearchQuery);

  const {
    currentTab,
    isTabLoaded,
    updateTab
  } = useTabState(pathname, urlTab);



  // Обновляем URL при изменении поиска
  useEffect(() => {
    const params = new URLSearchParams(searchParams.toString());
    
    if (debouncedQuery.trim()) {
      params.set("search", debouncedQuery);
    } else {
      params.delete("search");
    }
    
    // Сохраняем параметр таба
    if (urlTab) {
      params.set("tab", urlTab);
    }
    
    const newUrl = params.toString() ? `?${params.toString()}` : "";
    router.replace(`/agents${newUrl}`, { scroll: false });
  }, [debouncedQuery, router, searchParams, urlTab]);

  // Сохраняем таб в куки при изменении
  useEffect(() => {
    if (urlTab) {
      updateTab(urlTab);
    }
  }, [urlTab, updateTab]);

  // Обработчики поиска
  const handleSearchChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    updateQuery(e.target.value);
  }, [updateQuery]);

  const handleKeyDown = useCallback((e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      forceUpdate();
    }
  }, [forceUpdate]);

  // Fetch agents on mount
  useEffect(() => {
    const fetchAgents = async () => {
      try {
        setLoading(true);
        const { data: agentsData = [], error: apiError } = await listAgents();
        if (apiError) {
          setError(t("error.loadingData"));
        } else {
          setAgents(agentsData);
        }
      } catch (err) {
        setError(t("error.loadingData"));
      } finally {
        setLoading(false);
      }
    };

    fetchAgents();
  }, []);

  const columns = [
    {
      header: t("name"),
      render: (value: string) => (
        <div className="font-semibold truncate">
          {value}
        </div>
      ),
      accessor: "name",
    },
    {
      header: t("status"),
      accessor: "status",
      render: (value: string) => (
        <StatusBadge status={value} variant="agent" />
      ),
    },
    {
      header: t("model"),
      accessor: "model_id",
      render: (value: string, item: any) => (
        <ModelDisplay 
          modelId={item.model_id}
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
      render: (value: string, item: Agent) => {
        const toolAvatars = getToolAvatarUrls(item);
        return toolAvatars.length > 0 ? (
          <AvatarCircles
            maxDisplay={5}
            avatarUrls={toolAvatars}
          />
        ) : (
          <span className="text-xs text-muted-foreground">{t("noTools")}</span>
        );
      },
    },
    {
      header: "",
      accessor: "id",
      render: (value: string, item: any) => (
        <div className="flex gap-2">
          <Button 
            variant="default" 
            size="sm" 
            className="gap-2 bg-blue-600 hover:bg-blue-700 text-white"
            onClick={(e) => {
              e.stopPropagation();
              router.push(`/agents/${item.id}`);
            }}
          >
            Explore
          </Button>
          <Link href={`/agents/${item.id}/edit`} onClick={(e) => e.stopPropagation()}>
            <Button variant="ghost" size="sm" className="gap-1 text-muted-foreground hover:text-foreground">
              {commonT("edit")}
            </Button>
          </Link>
        </div>
      ),
    },
  ];

  // Фильтрация данных
  const filterData = useCallback((data: any[]) => {
    if (!debouncedQuery.trim()) return data;
    
    const query = debouncedQuery.toLowerCase();
    return data.filter(item => {
      return (
        item.name?.toLowerCase().includes(query) ||
        item.description?.toLowerCase().includes(query) ||
        item.model_id?.toLowerCase().includes(query) ||
        item.status?.toLowerCase().includes(query)
      );
    });
  }, [debouncedQuery]);

  const filteredAgents = useMemo(() => filterData(agents), [filterData, agents]);
  
  return (
    <ContentBlock 
      header={{
        breadcrumb: [
          {label: t("browseAgents")},
        ],
        description: t("mainDescriptionPage"),
        controls: (
          <Link href="/agents/create">
            <Button className="shrink-0 gap-2 shadow-sm" data-test="deploy-button">
              <Bot className="h-5 w-5" />
              {t("deployNewAgent")}
            </Button>
          </Link>
        )
    }}>
      {loading || (!isTabLoaded && !urlTab) ? (
        <div className="flex items-center justify-center h-32">
          <LoadingSpinner />
        </div>
      ) : (      
        <GridAndTableViews
          isEmpty={filteredAgents.length === 0}
          emptyState={<EmptyState
            iconsType="agent"
            title={t("noAgentsYet")}
            description={t("getStartedByAddingYourFirstAgent")}
            action={{
              label: t("addYourFirstAgent"),
              href: "/agents/create",
            }}
          />}
          searchParams={{
            ...Object.fromEntries(searchParams.entries()),
            tab: currentTab
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
                {isSearching ? (
                  <LoadingSpinner size="sm" text="" />
                ) : (
                  <Search className="h-4 w-4" />
                )}
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
    </ContentBlock>
  );
} 