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
import { LoadingSpinner } from "@/components/LoadingSpinner";

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
    },
    {
      header: "Description",
      accessor: "description",
      render: (value: string) => (
        <div className="max-w-xs truncate" title={value}>
          {value}
        </div>
      ),
    },
    {
      header: "Actions",
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

  // const mockAgents = [
  //   {
  //     id: "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  //     name: "Customer Support Agent",
  //     description: "AI-powered customer support agent that can handle inquiries, resolve issues, and provide product information",
  //     status: "active",
  //     instruction: "You are a helpful customer support agent. Always be polite and professional.",
  //     model_id: "gpt-4",
  //     icon: "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=64&h=64&fit=crop&crop=center",
  //     tools_config: {
  //       knowledge_base: {},
  //       ticket_system: {}
  //     },
  //     events_config: {
  //       notifications: {},
  //       logging: {}
  //     },
  //     planning: true
  //   },
  //   {
  //     id: "4fb96g75-6828-5673-c4gd-3d074g77bgb7",
  //     name: "Data Analysis Agent",
  //     description: "Specialized agent for data processing, analysis, and generating insights from complex datasets",
  //     status: "active",
  //     instruction: "You are a data analysis expert. Process data efficiently and provide clear insights.",
  //     model_id: "claude-3",
  //     icon: "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=64&h=64&fit=crop&crop=center",
  //     tools_config: {
  //       data_processor: {},
  //       visualization: {}
  //     },
  //     events_config: {
  //       progress_tracking: {},
  //       error_handling: {}
  //     },
  //     planning: true
  //   },
  //   {
  //     id: "5gc07h86-7939-6784-d5he-4e185h88chc8",
  //     name: "Content Creation Agent",
  //     description: "Creative agent for generating high-quality content, articles, and marketing materials",
  //     status: "inactive",
  //     instruction: "You are a creative content writer. Generate engaging and original content.",
  //     model_id: "gpt-4",
  //     icon: "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=64&h=64&fit=crop&crop=center",
  //     tools_config: {
  //       content_generator: {},
  //       plagiarism_checker: {}
  //     },
  //     events_config: {
  //       content_review: {},
  //       publishing: {}
  //     },
  //     planning: false
  //   },
  //   {
  //     id: "6hd18i97-8040-7895-e6if-5f296i99did9",
  //     name: "Task Automation Agent",
  //     description: "Automation specialist for handling repetitive tasks and workflow optimization",
  //     status: "active",
  //     instruction: "You are a task automation expert. Streamline processes and improve efficiency.",
  //     model_id: "claude-3",
  //     icon: "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=64&h=64&fit=crop&crop=center",
  //     tools_config: {
  //       workflow_engine: {},
  //       scheduler: {}
  //     },
  //     events_config: {
  //       task_monitoring: {},
  //       performance_metrics: {}
  //     },
  //     planning: true
  //   },
  //   {
  //     id: "7ie29j08-9151-8906-f7jg-6g307j00eje0",
  //     name: "Research Assistant Agent",
  //     description: "Research-focused agent for gathering information, analyzing sources, and compiling reports",
  //     status: "active",
  //     instruction: "You are a research assistant. Gather accurate information from reliable sources.",
  //     model_id: "gpt-4",
  //     icon: "https://images.unsplash.com/photo-1551288049-bebda4e38f71?w=64&h=64&fit=crop&crop=center",
  //     tools_config: {
  //       web_search: {},
  //       citation_manager: {}
  //     },
  //     events_config: {
  //       source_validation: {},
  //       report_generation: {}
  //     },
  //     planning: true
  //   }
  // ];

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
        itemLink={(agent) => `/agents/${agent.id}`}
        gridClassName="md:grid-cols-1 lg:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4"
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