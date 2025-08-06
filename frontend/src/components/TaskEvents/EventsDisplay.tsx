"use client";

import { useState, useMemo } from "react";
import { 
  AlertCircle, 
  AlertTriangle, 
  CheckCircle2, 
  Clock, 
  Filter,
  Info,
  Search,
  Calendar,
  ChevronDown,
  Activity,
  BarChart3,
  Zap
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { 
  Select, 
  SelectContent, 
  SelectItem, 
  SelectTrigger, 
  SelectValue 
} from "@/components/ui/select";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuCheckboxItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { ScrollArea } from "@/components/ui/scroll-area";
import { 
  DisplayEvent, 
  EventLevel, 
  WorkflowEventType, 
  EventFilters,
  EventStats,
  getEventLevelColor,
  getEventStats,
  EVENT_TYPE_CONFIG
} from "@/types/events";

interface EventsDisplayProps {
  events: DisplayEvent[];
  loading?: boolean;
  error?: string | null;
  connected?: boolean;
  onRefresh?: () => void;
  showFilters?: boolean;
  showStats?: boolean;
  maxHeight?: string;
}

const EventIcon = ({ type, level }: { type: WorkflowEventType; level: EventLevel }) => {
  const iconName = EVENT_TYPE_CONFIG[type]?.icon || "info";
  
  const iconMap = {
    "play-circle": <Zap className="h-4 w-4" />,
    "check-circle": <CheckCircle2 className="h-4 w-4" />,
    "x-circle": <AlertCircle className="h-4 w-4" />,
    "stop-circle": <Clock className="h-4 w-4" />,
    "refresh-cw": <Activity className="h-4 w-4" />,
    "check": <CheckCircle2 className="h-4 w-4" />,
    "brain": <BarChart3 className="h-4 w-4" />,
    "message-circle": <Info className="h-4 w-4" />,
    "alert-triangle": <AlertTriangle className="h-4 w-4" />,
    "tool": <Activity className="h-4 w-4" />,
    "check-square": <CheckCircle2 className="h-4 w-4" />,
    "alert-circle": <AlertCircle className="h-4 w-4" />,
    "dollar-sign": <BarChart3 className="h-4 w-4" />,
    "credit-card": <AlertTriangle className="h-4 w-4" />,
    "user-check": <Info className="h-4 w-4" />,
    "info": <Info className="h-4 w-4" />
  };
  
  return iconMap[iconName] || <Info className="h-4 w-4" />;
};

const EventLevelBadge = ({ level }: { level: EventLevel }) => {
  const config = {
    info: { label: "Info", className: "bg-blue-100 text-blue-800 dark:bg-blue-900/30 dark:text-blue-300" },
    success: { label: "Success", className: "bg-green-100 text-green-800 dark:bg-green-900/30 dark:text-green-300" },
    warning: { label: "Warning", className: "bg-yellow-100 text-yellow-800 dark:bg-yellow-900/30 dark:text-yellow-300" },
    error: { label: "Error", className: "bg-red-100 text-red-800 dark:bg-red-900/30 dark:text-red-300" }
  };
  
  const levelConfig = config[level];
  
  return (
    <Badge className={`px-2 py-0.5 text-xs ${levelConfig.className}`}>
      {levelConfig.label}
    </Badge>
  );
};

const EventStatsCard = ({ stats }: { stats: EventStats }) => (
  <Card className="mb-4">
    <CardHeader className="pb-3">
      <CardTitle className="text-base flex items-center gap-2">
        <BarChart3 className="h-4 w-4" />
        Event Summary
      </CardTitle>
    </CardHeader>
    <CardContent>
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <div className="text-center">
          <div className="text-2xl font-bold text-blue-600">{stats.total}</div>
          <div className="text-xs text-muted-foreground">Total Events</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold text-green-600">{stats.byLevel.success || 0}</div>
          <div className="text-xs text-muted-foreground">Success</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold text-red-600">{stats.byLevel.error || 0}</div>
          <div className="text-xs text-muted-foreground">Errors</div>
        </div>
        <div className="text-center">
          <div className="text-2xl font-bold text-orange-600">{stats.recentActivity}</div>
          <div className="text-xs text-muted-foreground">Last Hour</div>
        </div>
      </div>
    </CardContent>
  </Card>
);

export function EventsDisplay({
  events,
  loading = false,
  error = null,
  connected = false,
  onRefresh,
  showFilters = true,
  showStats = true,
  maxHeight = "600px"
}: EventsDisplayProps) {
  const [filters, setFilters] = useState<EventFilters>({});
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedLevels, setSelectedLevels] = useState<EventLevel[]>([]);
  const [selectedTypes, setSelectedTypes] = useState<WorkflowEventType[]>([]);

  // Filter events based on current filters
  const filteredEvents = useMemo(() => {
    return events.filter(event => {
      // Search filter
      if (searchQuery && !event.title.toLowerCase().includes(searchQuery.toLowerCase()) && 
          !event.description.toLowerCase().includes(searchQuery.toLowerCase())) {
        return false;
      }
      
      // Level filter
      if (selectedLevels.length > 0 && !selectedLevels.includes(event.level)) {
        return false;
      }
      
      // Type filter  
      if (selectedTypes.length > 0 && !selectedTypes.includes(event.type)) {
        return false;
      }
      
      return true;
    });
  }, [events, searchQuery, selectedLevels, selectedTypes]);

  const stats = useMemo(() => getEventStats(filteredEvents), [filteredEvents]);

  const formatTimestamp = (timestamp: Date) => {
    const now = new Date();
    const diff = now.getTime() - timestamp.getTime();
    const seconds = Math.floor(diff / 1000);
    const minutes = Math.floor(seconds / 60);
    const hours = Math.floor(minutes / 60);
    
    if (seconds < 60) return `${seconds}s ago`;
    if (minutes < 60) return `${minutes}m ago`;
    if (hours < 24) return `${hours}h ago`;
    return timestamp.toLocaleDateString();
  };

  if (error) {
    return (
      <Card className="border-red-200 bg-red-50 dark:bg-red-900/20">
        <CardContent className="pt-6">
          <div className="flex items-center gap-2 text-red-600">
            <AlertCircle className="h-4 w-4" />
            <span className="font-medium">Failed to load events</span>
          </div>
          <p className="text-sm text-red-600/80 mt-1">{error}</p>
          {onRefresh && (
            <Button variant="outline" size="sm" onClick={onRefresh} className="mt-3">
              Try Again
            </Button>
          )}
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4">
      {/* Connection Status */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className={`w-2 h-2 rounded-full ${connected ? 'bg-green-500' : 'bg-red-500'}`} />
          <span className="text-sm text-muted-foreground">
            {connected ? 'Live updates connected' : 'Not connected'}
          </span>
        </div>
        {onRefresh && (
          <Button variant="outline" size="sm" onClick={onRefresh} disabled={loading}>
            <Activity className="h-3 w-3 mr-1" />
            Refresh
          </Button>
        )}
      </div>

      {/* Stats Card */}
      {showStats && <EventStatsCard stats={stats} />}

      {/* Filters */}
      {showFilters && (
        <Card>
          <CardContent className="pt-4">
            <div className="flex flex-wrap gap-3">
              {/* Search */}
              <div className="flex-1 min-w-[200px]">
                <div className="relative">
                  <Search className="absolute left-2 top-1/2 transform -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                  <Input
                    placeholder="Search events..."
                    value={searchQuery}
                    onChange={(e) => setSearchQuery(e.target.value)}
                    className="pl-8"
                  />
                </div>
              </div>

              {/* Level Filter */}
              <DropdownMenu>
                <DropdownMenuTrigger asChild>
                  <Button variant="outline" size="sm" className="gap-1">
                    <Filter className="h-3 w-3" />
                    Level {selectedLevels.length > 0 && `(${selectedLevels.length})`}
                    <ChevronDown className="h-3 w-3" />
                  </Button>
                </DropdownMenuTrigger>
                <DropdownMenuContent>
                  <DropdownMenuLabel>Filter by Level</DropdownMenuLabel>
                  <DropdownMenuSeparator />
                  {(["info", "success", "warning", "error"] as EventLevel[]).map((level) => (
                    <DropdownMenuCheckboxItem
                      key={level}
                      checked={selectedLevels.includes(level)}
                      onCheckedChange={(checked) => {
                        if (checked) {
                          setSelectedLevels([...selectedLevels, level]);
                        } else {
                          setSelectedLevels(selectedLevels.filter(l => l !== level));
                        }
                      }}
                    >
                      {level.charAt(0).toUpperCase() + level.slice(1)}
                    </DropdownMenuCheckboxItem>
                  ))}
                </DropdownMenuContent>
              </DropdownMenu>

              {/* Clear Filters */}
              {(searchQuery || selectedLevels.length > 0 || selectedTypes.length > 0) && (
                <Button 
                  variant="ghost" 
                  size="sm" 
                  onClick={() => {
                    setSearchQuery("");
                    setSelectedLevels([]);
                    setSelectedTypes([]);
                  }}
                >
                  Clear
                </Button>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Events List */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-base">
            Events ({filteredEvents.length})
          </CardTitle>
        </CardHeader>
        <CardContent>
          <ScrollArea style={{ height: maxHeight }}>
            {loading && filteredEvents.length === 0 ? (
              <div className="flex items-center justify-center py-8">
                <div className="text-center">
                  <Activity className="h-8 w-8 animate-spin mx-auto mb-2 text-muted-foreground" />
                  <p className="text-sm text-muted-foreground">Loading events...</p>
                </div>
              </div>
            ) : filteredEvents.length === 0 ? (
              <div className="text-center py-8">
                <Calendar className="h-12 w-12 mx-auto mb-4 text-muted-foreground opacity-50" />
                <h3 className="text-lg font-semibold mb-2">No Events</h3>
                <p className="text-muted-foreground">
                  {events.length === 0 
                    ? "No events have been recorded for this task yet."
                    : "No events match your current filters."}
                </p>
              </div>
            ) : (
              <div className="space-y-3">
                {filteredEvents.map((event) => (
                  <div
                    key={event.id}
                    className={`flex items-start gap-3 p-3 rounded-lg border ${getEventLevelColor(event.level)}`}
                  >
                    <div className="flex-shrink-0 mt-0.5">
                      <EventIcon type={event.type} level={event.level} />
                    </div>
                    
                    <div className="flex-1 min-w-0">
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex-1">
                          <h4 className="text-sm font-medium mb-1">{event.title}</h4>
                          <p className="text-xs text-muted-foreground">{event.description}</p>
                        </div>
                        <div className="flex-shrink-0 text-right">
                          <EventLevelBadge level={event.level} />
                          <div className="text-xs text-muted-foreground mt-1">
                            {formatTimestamp(event.timestamp)}
                          </div>
                        </div>
                      </div>
                      
                      {event.data && Object.keys(event.data).length > 0 && (
                        <details className="mt-2">
                          <summary className="text-xs cursor-pointer text-muted-foreground hover:text-foreground">
                            Show details
                          </summary>
                          <div className="mt-1 p-2 bg-background/50 rounded text-xs font-mono">
                            <pre className="whitespace-pre-wrap">
                              {JSON.stringify(event.data, null, 2)}
                            </pre>
                          </div>
                        </details>
                      )}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </ScrollArea>
        </CardContent>
      </Card>
    </div>
  );
}

export default EventsDisplay;