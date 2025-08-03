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
    <div className="bg-white dark:bg-gray-900 border border-gray-200 dark:border-gray-700 rounded-2xl p-6 mb-8 shadow-sm">
      <div className="flex flex-col lg:flex-row gap-4">
        {/* Enhanced Search */}
        <div className="flex-1">
          <div className="relative">
            <div className="absolute inset-y-0 left-0 flex items-center pl-4 pointer-events-none">
              <Search className="h-5 w-5 text-gray-400" />
            </div>
            <Input
              placeholder="Search tasks by description, agent name, or task ID..."
              defaultValue={searchQuery}
              onChange={(e) => handleSearchChange(e.target.value)}
              className="pl-12 h-12 bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-700 rounded-xl text-base placeholder:text-gray-500 focus:ring-2 focus:ring-primary/20 focus:border-primary transition-all duration-200"
            />
          </div>
        </div>

        {/* Enhanced Filter Controls */}
        <div className="flex gap-3">
          <Select value={statusFilter} onValueChange={handleStatusChange}>
            <SelectTrigger className="w-[200px] h-12 bg-gray-50 dark:bg-gray-800 border-gray-200 dark:border-gray-700 rounded-xl">
              <div className="flex items-center gap-2">
                <Filter className="h-4 w-4 text-gray-500" />
                <SelectValue placeholder="Filter by status" />
              </div>
            </SelectTrigger>
            <SelectContent className="rounded-xl shadow-lg border-gray-200 dark:border-gray-700">
              <SelectItem value="all" className="rounded-lg">
                <div className="flex items-center gap-2">
                  <div className="w-2 h-2 rounded-full bg-gray-400" />
                  <span>All Statuses</span>
                </div>
              </SelectItem>
              {TASK_STATUSES.map((status) => (
                <SelectItem key={status} value={status} className="rounded-lg">
                  <div className="flex items-center gap-2">
                    <div className={`w-2 h-2 rounded-full ${
                      status === "running" ? "bg-blue-500" :
                      status === "completed" || status === "success" ? "bg-green-500" :
                      status === "paused" ? "bg-yellow-500" :
                      status === "failed" || status === "error" ? "bg-red-500" :
                      "bg-gray-400"
                    }`} />
                    <span>{status.charAt(0).toUpperCase() + status.slice(1)}</span>
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>

          {hasActiveFilters && (
            <Button
              variant="outline"
              onClick={clearFilters}
              className="h-12 px-4 gap-2 rounded-xl border-gray-200 dark:border-gray-700 hover:bg-gray-50 dark:hover:bg-gray-800 transition-colors duration-200"
            >
              <X className="h-4 w-4" />
              <span className="hidden sm:inline">Clear Filters</span>
            </Button>
          )}
        </div>
      </div>

      {/* Active Filters Display */}
      {hasActiveFilters && (
        <div className="flex flex-wrap items-center gap-2 mt-4 pt-4 border-t border-gray-100 dark:border-gray-800">
          <span className="text-sm text-gray-600 dark:text-gray-400">Active filters:</span>
          {searchQuery && (
            <div className="flex items-center gap-1 bg-blue-50 dark:bg-blue-900/20 text-blue-700 dark:text-blue-300 px-3 py-1 rounded-full text-sm">
              <Search className="h-3 w-3" />
              <span>"{searchQuery}"</span>
              <button
                onClick={() => handleSearchChange("")}
                className="ml-1 hover:bg-blue-100 dark:hover:bg-blue-800 rounded-full p-0.5"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          )}
          {statusFilter !== "all" && (
            <div className="flex items-center gap-1 bg-purple-50 dark:bg-purple-900/20 text-purple-700 dark:text-purple-300 px-3 py-1 rounded-full text-sm">
              <Filter className="h-3 w-3" />
              <span>{statusFilter.charAt(0).toUpperCase() + statusFilter.slice(1)}</span>
              <button
                onClick={() => handleStatusChange("all")}
                className="ml-1 hover:bg-purple-100 dark:hover:bg-purple-800 rounded-full p-0.5"
              >
                <X className="h-3 w-3" />
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}