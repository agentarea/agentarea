import React from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Bot, Search, Filter, ArrowUpDown, Zap } from "lucide-react";
import Link from "next/link";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { listAgents } from "@/lib/api";
import EmptyState from "@/components/EmptyState/EmptyState";
import ContentBlock from "@/components/ContentBlock/ContentBlock";

const categories = ["All"];

interface AgentsBrowsePageProps {
  searchParams?: { search?: string; category?: string };
}

export default async function AgentsBrowsePage({ searchParams: searchParamsPromise }: AgentsBrowsePageProps) {
  // Fetch agents server-side
  const { data: agents = [], error } = await listAgents();

  const searchParams = await searchParamsPromise;

  // Get search query and category from searchParams (URL)
  const searchQuery = searchParams?.search || "";
  const selectedCategory = searchParams?.category || "All";

  // Filter by search query
  const filteredAgents = agents.filter(agent =>
    agent.name.toLowerCase().includes(searchQuery.toLowerCase())
  );

  return (
    <ContentBlock 
      header={{
        title: "Browse Agents",
        description: "Discover and deploy automation agents for your workflow needs",
        controls: (
          <Link href="/agents/create">
            <Button className="shrink-0 gap-2 shadow-sm" data-test="deploy-button">
              <Bot className="h-5 w-5" />
              Deploy New Agent
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
                <form action="" method="get">
                  <Input
                    name="search"
                    placeholder="Search agents by name or capability..."
                    className="pl-10 h-11"
                    defaultValue={searchQuery}
                  />
                </form>
              </div>
              <Button variant="outline" className="h-11 gap-2" aria-label="Filter agents">
                <Filter className="h-4 w-4" />
                <span className="hidden sm:inline">Filter</span>
              </Button>
              <Button variant="outline" className="h-11 gap-2" aria-label="Sort agents">
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

          {error ? (
            <div className="text-center py-10 text-destructive">Failed to load agents</div>
          ) : filteredAgents.length === 0 ? (
            <EmptyState
              iconsType="agent"
              title="No agents yet"
              description="Get started by adding your first agent."
              action={{
                label: "Add your first agent",
                href: "/agents/create",
              }}
            />
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-6">
              {filteredAgents.map((agent) => (
                <Card 
                  key={agent.id} 
                  className="p-6 hover:shadow-md transition-all border border-border/40 hover:border-border group"
                >
                  <div className="flex items-start justify-between mb-4">
                    <div className="flex items-center gap-3">
                      <div className="h-12 w-12 bg-primary/10 rounded-full flex items-center justify-center">
                        <Bot className="h-6 w-6 text-primary" />
                      </div>
                      <div>
                        <h3 className="font-medium text-lg group-hover:text-primary transition-colors">{agent.name}</h3>
                        <div className="mt-1 flex flex-wrap gap-1">
                          {/* {agent.capabilities.map((cap, i) => (
                            <Badge key={i} variant="secondary" className="font-normal">{cap}</Badge>
                          ))} */}
                        </div>
                      </div>
                    </div>
                    <Badge variant={
                      agent.status === "running" ? "default" :
                      agent.status === "stopped" ? "destructive" : "outline"
                    }>
                      {agent.status === "running" && <Zap className="h-3 w-3 mr-1" />}
                      {agent.status}
                    </Badge>
                  </div>
                  <div className="flex justify-end items-center mt-auto">
                    <Button variant="ghost" size="sm" className="text-primary hover:text-primary font-normal">
                      View Details
                    </Button>
                  </div>
                </Card>
              ))}
            </div>
          )}
        </div>
      </ContentBlock>
  );
} 