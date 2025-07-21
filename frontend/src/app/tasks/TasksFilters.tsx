"use client";

import React from "react";
import { useRouter } from "next/navigation";
import { Search, Filter, X } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";

// Define all possible task statuses
const TASK_STATUSES = [
  "running",
  "completed", 
  "success",
  "failed",
  "error",
  "paused",
  "pending",
  "cancelled"
] as const;

interface TasksFiltersProps {
  searchQuery: string;
  statusFilter: string;
  hasActiveFilters: boolean;
}

export function TasksFilters({ 
  searchQuery, 
  statusFilter, 
  hasActiveFilters 
}: TasksFiltersProps) {
  const router = useRouter();

  const updateFilters = (newSearch?: string, newStatus?: string) => {
    const params = new URLSearchParams();
    
    const search = newSearch !== undefined ? newSearch : searchQuery;
    const status = newStatus !== undefined ? newStatus : statusFilter;
    
    if (search) params.set("search", search);
    if (status !== "all") params.set("status", status);
    
    const newUrl = params.toString() ? `?${params.toString()}` : "";
    router.replace(`/tasks${newUrl}`, { scroll: false });
  };

  const handleSearchChange = (value: string) => {
    updateFilters(value, undefined);
  };

  const handleStatusChange = (value: string) => {
    updateFilters(undefined, value);
  };

  const clearFilters = () => {
    router.replace("/tasks", { scroll: false });
  };

  return (
    <div className="flex flex-col sm:flex-row gap-4 mb-6">
      <div className="flex-1 relative">
        <Search className="absolute left-3 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
        <Input
          placeholder="Search tasks by description or agent name..."
          defaultValue={searchQuery}
          onChange={(e) => handleSearchChange(e.target.value)}
          className="pl-10"
        />
      </div>
      <div className="flex gap-2">
        <Select value={statusFilter} onValueChange={handleStatusChange}>
          <SelectTrigger className="w-[180px]">
            <Filter className="h-4 w-4 mr-2" />
            <SelectValue placeholder="Filter by status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Statuses</SelectItem>
            {TASK_STATUSES.map((status) => (
              <SelectItem key={status} value={status}>
                {status.charAt(0).toUpperCase() + status.slice(1)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {hasActiveFilters && (
          <Button
            variant="outline"
            size="sm"
            onClick={clearFilters}
            className="gap-1"
          >
            <X className="h-4 w-4" />
            Clear
          </Button>
        )}
      </div>
    </div>
  );
}