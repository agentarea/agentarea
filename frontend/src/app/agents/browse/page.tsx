"use client";

import React, { useState, useEffect } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Bot, Search, Filter, ArrowUpDown, Zap, Edit } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { listAgents } from "@/lib/api";
import EmptyState from "@/components/EmptyState/EmptyState";
import ContentBlock from "@/components/ContentBlock/ContentBlock";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

const categories = ["All"];

interface Agent {
  id: string;
  name: string;
  description?: string | null;
  status: string;
}

export default function AgentsBrowsePage() {
  const t = useTranslations("Agent");
  const [agents, setAgents] = useState<Agent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedCategory] = useState("All");
  const router = useRouter();

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

  // Filter by search query
  const filteredAgents = agents.filter(agent =>
    agent.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <ContentBlock 
      header={{
        // title: "Browse Agents",
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

        {/* Main content area */}
        <div className="w-full">
          <div className="space-y-6 mb-8">
            <div className="grid grid-cols-1 lg:grid-cols-[1fr,auto,auto] gap-4">
              <div className="relative">
                <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
                <Input
                  placeholder="Search agents by name or capability..."
                  className="pl-10 h-11"
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                />
              </div>
              <Button variant="outline" className="h-11 gap-2" aria-label="Filter agents" disabled>
                <Filter className="h-4 w-4" />
                <span className="hidden sm:inline">Filter</span>
              </Button>
              <Button variant="outline" className="h-11 gap-2" aria-label="Sort agents" disabled>
                <ArrowUpDown className="h-4 w-4" />
                <span className="hidden sm:inline">Sort</span>
              </Button>
            </div>

            <Tabs defaultValue="All" className="w-full">
              <TabsList className="flex w-full h-auto flex-wrap gap-2 bg-transparent">
                {categories.map((category) => (
                  <TabsTrigger
                    key={category}
                    value={category}
                    className={`rounded-full px-4 py-2 transition-all ${
                      selectedCategory === category 
                      ? "bg-primary text-primary-foreground" 
                      : "bg-secondary hover:bg-secondary/80"
                    }`}
                  >
                    {category}
                  </TabsTrigger>
                ))}
              </TabsList>
            </Tabs>
          </div>

          {loading ? (
            <div className="text-center py-10">
              <div className="inline-block h-6 w-6 animate-spin rounded-full border-2 border-solid border-current border-r-transparent"></div>
              <p className="mt-2 text-muted-foreground">Loading agents...</p>
            </div>
          ) : error ? (
            <div className="text-center py-10 text-destructive">Failed to load agents</div>
          ) : filteredAgents.length === 0 ? (
            <EmptyState
              iconsType="agent"
              title={t("noAgentsYet")}
              description={t("getStartedByAddingYourFirstAgent")}
              action={{
                label: t("addYourFirstAgent"),
                href: "/agents/create",
              }}
            />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
              {filteredAgents.map((agent) => (
                <Card 
                  key={agent.id} 
                  className="p-6 hover:shadow-lg transition-all border border-border/40 hover:border-primary/20 group cursor-pointer"
                  onClick={() => router.push(`/agents/${agent.id}`)}
                >
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-3">
                      <div className="h-12 w-12 bg-primary/10 rounded-full flex items-center justify-center group-hover:bg-primary/20 transition-colors">
                        <Bot className="h-6 w-6 text-primary" />
                      </div>
                      <div className="flex-1">
                        <h3 className="font-semibold text-lg group-hover:text-primary transition-colors">{agent.name}</h3>
                        <p className="text-sm text-muted-foreground mt-1 line-clamp-2">
                          {agent.description || "A versatile automation agent ready to help with your tasks"}
                        </p>
                      </div>
                    </div>
                    <Badge variant={
                      agent.status === "active" ? "default" :
                      agent.status === "inactive" ? "destructive" : "outline"
                    }>
                      {agent.status === "active" && <Zap className="h-3 w-3 mr-1" />}
                      {agent.status}
                    </Badge>
                  </div>
                  
                  {/* Agent capabilities/features */}
                  <div className="mb-4">
                    <div className="flex flex-wrap gap-1">
                      <Badge variant="secondary" className="text-xs">
                        Chat Enabled
                      </Badge>
                      <Badge variant="secondary" className="text-xs">
                        Task Automation
                      </Badge>
                      {agent.status === "active" && (
                        <Badge variant="secondary" className="text-xs bg-green-100 text-green-700">
                          Ready
                        </Badge>
                      )}
                    </div>
                  </div>
                  
                  <div className="flex justify-between items-center mt-auto gap-2">
                    <div className="flex gap-2">
                      <Link href={`/agents/${agent.id}`} onClick={(e) => e.stopPropagation()}>
                        <Button variant="default" size="sm" className="gap-2">
                          <Bot className="h-4 w-4" />
                          Chat Now
                        </Button>
                      </Link>
                      <Link href={`/agents/${agent.id}`} onClick={(e) => e.stopPropagation()}>
                        <Button variant="outline" size="sm" className="gap-2">
                          View Details
                        </Button>
                      </Link>
                    </div>
                    <Link href={`/agents/${agent.id}/edit`} onClick={(e) => e.stopPropagation()}>
                      <Button variant="ghost" size="sm" className="gap-1 text-muted-foreground hover:text-foreground">
                        <Edit className="h-3 w-3" />
                        Edit
                      </Button>
                    </Link>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>
      </ContentBlock>
  );
} 