"use client";

import { Bot, Plug, Sparkles, Zap, RefreshCw, Shield } from "lucide-react";
import { Button } from "@/components/ui/button";

interface NetworkToolbarProps {
  filters: Record<string, boolean>;
  onFilterToggle: (type: string) => void;
  onRefresh: () => void;
  loading: boolean;
  hasGovernance: boolean;
  showGovernance: boolean;
  onToggleGovernance: () => void;
}

const FILTER_CONFIG = [
  { key: "agent", label: "Agents", icon: Bot, color: "text-blue-500" },
  { key: "mcp_instance", label: "MCPs", icon: Plug, color: "text-green-500" },
  { key: "skill", label: "Skills", icon: Sparkles, color: "text-purple-500" },
  { key: "trigger", label: "Triggers", icon: Zap, color: "text-amber-500" },
];

export default function NetworkToolbar({
  filters,
  onFilterToggle,
  onRefresh,
  loading,
  hasGovernance,
  showGovernance,
  onToggleGovernance,
}: NetworkToolbarProps) {
  return (
    <div className="flex items-center gap-1 rounded-lg border bg-white/95 p-1 shadow-sm backdrop-blur dark:bg-zinc-800/95 dark:border-zinc-700">
      {FILTER_CONFIG.map(({ key, label, icon: Icon, color }) => (
        <Button
          key={key}
          variant={filters[key] ? "secondary" : "ghost"}
          size="sm"
          onClick={() => onFilterToggle(key)}
          className={`gap-1 text-xs h-7 px-2 ${!filters[key] ? "opacity-40" : ""}`}
          aria-label={`Toggle ${label}`}
        >
          <Icon className={`h-3.5 w-3.5 ${color}`} />
          {label}
        </Button>
      ))}

      <div className="mx-1 h-5 w-px bg-border" />

      {hasGovernance && (
        <Button
          variant={showGovernance ? "secondary" : "ghost"}
          size="sm"
          onClick={onToggleGovernance}
          className="gap-1 text-xs h-7 px-2"
          aria-label="Toggle governance"
        >
          <Shield className="h-3.5 w-3.5" />
          Gov
        </Button>
      )}

      <Button
        variant="ghost"
        size="icon"
        className="h-7 w-7"
        onClick={onRefresh}
        disabled={loading}
      >
        <RefreshCw className={`h-3.5 w-3.5 ${loading ? "animate-spin" : ""}`} />
      </Button>
    </div>
  );
}
