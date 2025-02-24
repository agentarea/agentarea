"use client";

import React, { useEffect, useState } from "react";
import { Card } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  Search,
  Filter,
  ArrowUpDown,
  RefreshCw,
  Settings,
  Plus,
  Lock,
  Building2,
  LayoutGrid,
  Table as TableIcon,
} from "lucide-react";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { useRouter } from "next/navigation";
import { 
  mockDataSources,
  statusColors,
  typeColors
} from "../_mocks/data";
import { sourcesApi, SourceResponse } from '@/api/sources';
import { LoadingSpinner } from '@/components/LoadingSpinner';

type FilterType = "all" | "setup" | "available" | "own" | "delegated" | "private" | "shared";

export default function SourcesBrowsePage() {
  const router = useRouter();
  const [viewMode, setViewMode] = React.useState<"grid" | "table">("grid");
  const [selectedFilter, setSelectedFilter] = React.useState<FilterType>("all");
  const [sources, setSources] = useState<SourceResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const handleViewModeChange = (value: string) => {
    setViewMode(value as "grid" | "table");
  };

  const filteredSources = React.useMemo(() => {
    if (selectedFilter === "all") return mockDataSources;
    if (selectedFilter === "setup") return mockDataSources.filter(s => s.isSetup);
    if (selectedFilter === "available") return mockDataSources.filter(s => !s.isSetup);
    if (selectedFilter === "own") return mockDataSources.filter(s => s.ownership === "own");
    if (selectedFilter === "delegated") return mockDataSources.filter(s => s.ownership === "delegated");
    if (selectedFilter === "private") return mockDataSources.filter(s => s.visibility === "private");
    return mockDataSources.filter(s => s.visibility === "shared");
  }, [selectedFilter]);

  useEffect(() => {
    loadSources();
  }, []);

  async function loadSources() {
    try {
      const data = await sourcesApi.listSources();
      setSources(data);
    } catch (err) {
      setError('Failed to load sources');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  if (loading) return <LoadingSpinner />;
  if (error) return <div className="text-red-500">{error}</div>;

  return (
    <div className="p-8">
      <div className="flex justify-between items-center mb-8">
        <div>
          <h1 className="text-4xl font-bold">Data Sources</h1>
          <p className="text-lg text-muted-foreground mt-2">
            Manage your connected data sources and integrations
          </p>
        </div>
        <div className="flex gap-4">
          <Button variant="outline" className="flex items-center gap-2">
            <RefreshCw className="h-4 w-4" />
            Refresh All
          </Button>
          <Button className="flex items-center gap-2">
            <Plus className="h-5 w-5" />
            Add New Source
          </Button>
        </div>
      </div>

      <div className="flex flex-col gap-6 mb-6">
        <div className="flex justify-between items-center">
          <div className="flex gap-4 flex-1">
            <div className="relative flex-1">
              <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 text-muted-foreground h-4 w-4" />
              <Input
                placeholder="Search sources..."
                className="pl-10"
              />
            </div>
            <Button variant="outline" className="flex items-center gap-2">
              <Filter className="h-4 w-4" />
              Filter
            </Button>
            <Button variant="outline" className="flex items-center gap-2">
              <ArrowUpDown className="h-4 w-4" />
              Sort
            </Button>
          </div>
          <Tabs value={viewMode} onValueChange={handleViewModeChange}>
            <TabsList>
              <TabsTrigger value="grid">
                <LayoutGrid className="h-4 w-4" />
              </TabsTrigger>
              <TabsTrigger value="table">
                <TableIcon className="h-4 w-4" />
              </TabsTrigger>
            </TabsList>
          </Tabs>
        </div>

        <div className="flex gap-4">
          <Badge 
            variant={selectedFilter === "all" ? "default" : "outline"} 
            className="cursor-pointer hover:bg-secondary/80"
            onClick={() => setSelectedFilter("all")}
          >
            All Sources
          </Badge>
          <Badge 
            variant={selectedFilter === "setup" ? "default" : "outline"} 
            className="cursor-pointer hover:bg-secondary/80"
            onClick={() => setSelectedFilter("setup")}
          >
            Setup Ready
          </Badge>
          <Badge 
            variant={selectedFilter === "available" ? "default" : "outline"} 
            className="cursor-pointer hover:bg-secondary/80"
            onClick={() => setSelectedFilter("available")}
          >
            Available
          </Badge>
          <Badge 
            variant={selectedFilter === "own" ? "default" : "outline"} 
            className="cursor-pointer hover:bg-secondary/80"
            onClick={() => setSelectedFilter("own")}
          >
            Own Sources
          </Badge>
          <Badge 
            variant={selectedFilter === "delegated" ? "default" : "outline"} 
            className="cursor-pointer hover:bg-secondary/80"
            onClick={() => setSelectedFilter("delegated")}
          >
            Delegated
          </Badge>
        </div>
      </div>

      {viewMode === "grid" ? (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
          {sources.map((source) => (
            <Card 
              key={source.source_id} 
              className="p-6 hover:shadow-lg transition-shadow duration-200 cursor-pointer"
              onClick={() => router.push(`/sources/${source.source_id}`)}
            >
              <div className="flex items-start justify-between mb-4">
                <div className="flex items-center gap-3">
                  <div className={`h-12 w-12 rounded-lg flex items-center justify-center ${typeColors[source.type]}`}>
                    {source.icon}
                  </div>
                  <div>
                    <div className="flex items-center gap-2">
                      <h3 className="font-semibold">{source.name}</h3>
                      {source.visibility === "private" && (
                        <Lock className="h-4 w-4 text-muted-foreground" />
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <span className={`text-xs px-2 py-1 rounded-full ${typeColors[source.type]}`}>
                        {source.type}
                      </span>
                    </div>
                  </div>
                </div>
                <div className={`flex items-center gap-2 px-3 py-1 rounded-full ${statusColors[source.status]}`}>
                  {source.status === "connected" ? "✔" : source.status === "disconnected" ? "✗" : "⟳"}
                  <span className="text-sm capitalize">{source.status.replace('_', ' ')}</span>
                </div>
              </div>
              <p className="text-sm text-muted-foreground mb-4">{source.description}</p>
              <div className="flex flex-col gap-2 mb-4">
                <div className="flex items-center gap-2">
                  <Building2 className="h-4 w-4 text-muted-foreground" />
                  <span className="text-sm">{source.sourceOrg}</span>
                </div>
                <div className="flex flex-wrap gap-2">
                  {source.resourceTypes.map((type) => (
                    <Badge key={type} variant="secondary">
                      {type}
                    </Badge>
                  ))}
                </div>
              </div>
              <div className="flex justify-between items-center text-sm">
                <div>
                  <p className="font-medium">Last Sync</p>
                  <p className="text-muted-foreground">{source.lastSync}</p>
                </div>
                <div className="text-right">
                  <p className="font-medium">Data Points</p>
                  <p className="text-muted-foreground">{source.dataPoints}</p>
                </div>
              </div>
              <div className="mt-4 pt-4 border-t flex justify-end gap-2" onClick={e => e.stopPropagation()}>
                <Button variant="ghost" size="icon" title="Refresh">
                  <RefreshCw className="h-4 w-4" />
                </Button>
                <Button variant="ghost" size="icon" title="Settings">
                  <Settings className="h-4 w-4" />
                </Button>
              </div>
            </Card>
          ))}
        </div>
      ) : (
        <div className="rounded-md border">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Source</TableHead>
                <TableHead>Type</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Organization</TableHead>
                <TableHead>Resources</TableHead>
                <TableHead>Last Sync</TableHead>
                <TableHead>Actions</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {sources.map((source) => (
                <TableRow 
                  key={source.source_id} 
                  className="cursor-pointer hover:bg-secondary/50"
                  onClick={() => router.push(`/sources/${source.source_id}`)}
                >
                  <TableCell>
                    <div className="flex items-center gap-3">
                      <div className="h-8 w-8 bg-primary/10 rounded-lg flex items-center justify-center">
                        {source.icon}
                      </div>
                      <div>
                        <div className="flex items-center gap-2">
                          <span className="font-medium">{source.name}</span>
                          {source.visibility === "private" && (
                            <Lock className="h-4 w-4 text-muted-foreground" />
                          )}
                        </div>
                        <span className="text-sm text-muted-foreground">{source.description}</span>
                      </div>
                    </div>
                  </TableCell>
                  <TableCell>{source.type}</TableCell>
                  <TableCell>
                    <div className={`inline-flex items-center gap-2 px-3 py-1 rounded-full ${statusColors[source.status]}`}>
                      {source.status === "connected" ? "✔" : source.status === "disconnected" ? "✗" : "⟳"}
                      <span className="capitalize">{source.status.replace('_', ' ')}</span>
                    </div>
                  </TableCell>
                  <TableCell>{source.sourceOrg}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {source.resourceTypes.map((type) => (
                        <Badge key={type} variant="secondary">
                          {type}
                        </Badge>
                      ))}
                    </div>
                  </TableCell>
                  <TableCell>{source.lastSync}</TableCell>
                  <TableCell>
                    <div className="flex gap-2" onClick={e => e.stopPropagation()}>
                      <Button variant="ghost" size="icon" title="Refresh">
                        <RefreshCw className="h-4 w-4" />
                      </Button>
                      <Button variant="ghost" size="icon" title="Settings">
                        <Settings className="h-4 w-4" />
                      </Button>
                    </div>
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </div>
      )}
    </div>
  );
} 