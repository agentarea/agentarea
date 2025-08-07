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
import { useSearchWithDebounce, useTabState } from "../../../hooks";
import { AvatarCircles } from "@/components/ui/avatar-circles";
import { LoadingSpinner } from "@/components/LoadingSpinner";
import ModelDisplay from "@/app/agents/browse/components/ModelDisplay";

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
    router.replace(`/agents/browse${newUrl}`, { scroll: false });
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
          setError("Failed to load agents");
        } else {
          setAgents(agentsData);
        }
      } catch (err) {
        setError("Failed to load agents");
      } finally {
        setLoading(false);
      }
    };

    fetchAgents();
  }, []);

  const columns = [
    {
      header: "Name",
      render: (value: string) => (
        <div className="font-semibold truncate">
          {value}
        </div>
      ),
      accessor: "name",
    },
    {
      header: "Status",
      accessor: "status",
      render: (value: string) => (
        <StatusBadge status={value} variant="agent" />
      ),
    },
    {
      header: "Model",
      accessor: "model_id",
      render: (value: string, item: any) => (
        <ModelDisplay 
          modelId={item.model_id}
        />
      ),
    },
    {
      header: "Description",
      accessor: "description",
      render: (value: string) => (
        <div className="max-w-xs truncate note" title={value}>
          {value}
        </div>
      ),
    },
    {
      header: "Tools (MCPs)",
      accessor: "tools",
      render: (value: string) => (
      // FIX DATA for avatar urls 
        <AvatarCircles
          maxDisplay={5}
          avatarUrls={[
              {
                  imageUrl: "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQ2sSeQqjaUTuZ3gRgkKjidpaipF_l6s72lBw&s",
              },
              {
                  imageUrl: "https://cdn.worldvectorlogo.com/logos/jira-1.svg",
              },
              {
                  imageUrl: "https://encrypted-tbn0.gstatic.com/images?q=tbn:ANd9GcQiiqczgVWrWg2wpS5wC5iW2u3ppLqauc10yw&s",
              },{
                  imageUrl: "https://upload.wikimedia.org/wikipedia/commons/thumb/e/e9/Notion-logo.svg/2048px-Notion-logo.svg.png",
              },
              {
                  imageUrl: "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=64&h=64&fit=crop&crop=center",
              },
              {
                  imageUrl: "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=64&h=64&fit=crop&crop=center",
              },
              {
                  imageUrl: "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=64&h=64&fit=crop&crop=center",
              }
          ]}
        />
      ),
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
              Edit
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

  // Не рендерим до загрузки таба для предотвращения мерцания
  if (!isTabLoaded && !urlTab) {
    return (
      <ContentBlock 
        header={{
          breadcrumb: [{label: t("browseAgents")}],
          description: t("description"),
          controls: (
            <Link href="/agents/create">
              <Button className="shrink-0 gap-2 shadow-sm" data-test="deploy-button">
                <Bot className="h-5 w-5" />
                {t("deployNewAgent")}
              </Button>
            </Link>
          )
        }}
      >
        <div className="flex items-center justify-center h-32">
          <LoadingSpinner />
        </div>
      </ContentBlock>
    );
  }

  return (
    <ContentBlock 
      header={{
        breadcrumb: [
          {label: t("browseAgents")},
        ],
        description: t("description"),
        controls: (
          <Link href="/agents/create">
            <Button className="shrink-0 gap-2 shadow-sm" data-test="deploy-button">
              <Bot className="h-5 w-5" />
              {t("deployNewAgent")}
            </Button>
          </Link>
        )
    }}>

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
        routeChange="/agents/browse"
        cardContent={(item) => <AgentCard agent={item} />}
        cardClassName="px-0 pb-0 overflow-hidden"
        itemLink={(agent) => `/agents/${agent.id}`}
        gridClassName="grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"
        leftComponent={
          <div className="relative w-full focus-within:w-full max-w-full transition-all duration-300">
            <div className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground">
              {isSearching ? (
                <div className="animate-spin rounded-full h-4 w-4 border-b-2 border-primary"></div>
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
    </ContentBlock>
  );
} 