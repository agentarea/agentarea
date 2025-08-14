"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";
import { 
  CheckCircle, 
  AlertCircle, 
  Settings, 
  Trash2, 
  ExternalLink, 
  Grid, 
  List, 
  AlertTriangle, 
  Loader2, 
  Copy, 
  FileText, 
  Brain,
  Wrench, 
  GitBranch, 
  Globe, 
  Database, 
  MessageSquare, 
  Bot, 
  Activity,
  Zap,
  Clock
} from "lucide-react";
import Link from "next/link";
import { getMCPHealthStatus } from "@/lib/api";

interface MCPInstance {
  id: string;
  name: string;
  description?: string | null;
  status: string;
  endpoint_url?: string;
  created_at: string;
  server_spec_id?: string | null;
  json_spec?: any;
}

interface HealthCheck {
  service_name: string;
  slug: string;
  url: string;
  healthy: boolean;
  http_reachable: boolean;
  response_time_ms: number;
  error?: string;
  timestamp: string;
  container_status: string;
}

interface MyMCPsSectionProps {
  mcpInstances: MCPInstance[];
}

// Helper function to get category icon based on name or type
const getCategoryIcon = (instance: MCPInstance) => {
  const name = instance.name.toLowerCase();
  if (name.includes('filesystem') || name.includes('file')) return FileText;
  if (name.includes('memory') || name.includes('knowledge')) return Brain;
  if (name.includes('git') || name.includes('github')) return GitBranch;
  if (name.includes('web') || name.includes('fetch') || name.includes('browser')) return Globe;
  if (name.includes('database') || name.includes('sql')) return Database;
  if (name.includes('slack') || name.includes('gmail') || name.includes('message')) return MessageSquare;
  if (name.includes('puppeteer') || name.includes('automation')) return Bot;
  return Wrench;
};

// Helper function to get category from instance name
const getCategory = (instance: MCPInstance) => {
  const name = instance.name.toLowerCase();
  if (name.includes('filesystem') || name.includes('file')) return 'Files';
  if (name.includes('memory') || name.includes('knowledge')) return 'AI';
  if (name.includes('git') || name.includes('github')) return 'Dev';
  if (name.includes('web') || name.includes('fetch') || name.includes('browser')) return 'Web';
  if (name.includes('database') || name.includes('sql')) return 'Data';
  if (name.includes('slack') || name.includes('gmail') || name.includes('message')) return 'Messaging';
  if (name.includes('puppeteer') || name.includes('automation')) return 'Tools';
  return 'Tools';
};

// Enhanced status display with better visual design
const getStatusDisplay = (status: string, healthCheck?: HealthCheck) => {
  if (healthCheck) {
    if (healthCheck.container_status === 'running' && healthCheck.healthy) {
      return { 
        text: 'Active', 
        variant: 'default' as const, 
        icon: CheckCircle, 
        color: 'text-green-500',
        bgColor: 'bg-green-50 border-green-200 dark:bg-green-950/30 dark:border-green-800',
        detail: `${healthCheck.response_time_ms}ms`,
        tooltip: 'Server is running and responding normally'
      };
    } else if (healthCheck.container_status === 'running' && !healthCheck.healthy) {
      return { 
        text: 'Error', 
        variant: 'destructive' as const, 
        icon: AlertTriangle, 
        color: 'text-red-500',
        bgColor: 'bg-red-50 border-red-200 dark:bg-red-950/30 dark:border-red-800',
        detail: 'Connection failed',
        tooltip: healthCheck.error || 'Health check failed'
      };
    } else if (healthCheck.container_status === 'stopped') {
      return { 
        text: 'Stopped', 
        variant: 'secondary' as const, 
        icon: AlertCircle, 
        color: 'text-gray-500',
        bgColor: 'bg-gray-50 border-gray-200 dark:bg-gray-950/30 dark:border-gray-800',
        detail: 'Not running',
        tooltip: 'Container is not running'
      };
    }
  }
  
  switch (status) {
    case 'running':
      return { 
        text: 'Active', 
        variant: 'default' as const, 
        icon: CheckCircle, 
        color: 'text-green-500',
        bgColor: 'bg-green-50 border-green-200 dark:bg-green-950/30 dark:border-green-800',
        tooltip: 'Server is running' 
      };
    case 'stopped':
      return { 
        text: 'Stopped', 
        variant: 'secondary' as const, 
        icon: AlertCircle, 
        color: 'text-gray-500',
        bgColor: 'bg-gray-50 border-gray-200 dark:bg-gray-950/30 dark:border-gray-800',
        tooltip: 'Server is stopped' 
      };
    case 'pending':
      return { 
        text: 'Starting', 
        variant: 'secondary' as const, 
        icon: Loader2, 
        color: 'text-amber-500',
        bgColor: 'bg-amber-50 border-amber-200 dark:bg-amber-950/30 dark:border-amber-800',
        detail: '~30s', 
        tooltip: 'Server is starting up' 
      };
    default:
      return { 
        text: 'Setup', 
        variant: 'outline' as const, 
        icon: Settings, 
        color: 'text-amber-500',
        bgColor: 'bg-amber-50 border-amber-200 dark:bg-amber-950/30 dark:border-amber-800',
        tooltip: 'Configuration required' 
      };
  }
};

export function MyMCPsSection({ mcpInstances }: MyMCPsSectionProps) {
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('list');
  const [showAll, setShowAll] = useState(false);
  const [healthChecks, setHealthChecks] = useState<HealthCheck[]>([]);
  const [healthLoading, setHealthLoading] = useState(true);

  // Copy to clipboard helper
  const copyToClipboard = async (text: string) => {
    try {
      await navigator.clipboard.writeText(text);
    } catch (err) {
      console.error('Failed to copy: ', err);
    }
  };

  // Get URL info helper
  const getUrlInfo = (instance: MCPInstance, healthCheck?: HealthCheck) => {
    if (healthLoading && !healthCheck) {
      return { url: null, displayText: null };
    }

    const url = healthCheck?.url || 
                instance.endpoint_url || 
                instance.json_spec?.url || 
                instance.json_spec?.endpoint_url ||
                null;
    
    const displayText = healthCheck?.slug || 
                       (url ? url.split('/').pop() || url : null);
    
    return { url, displayText };
  };

  // Health status polling
  useEffect(() => {
    const fetchHealthStatus = async () => {
      try {
        const healthData = await getMCPHealthStatus();
        setHealthChecks(healthData.health_checks);
      } catch (error) {
        console.error('Failed to fetch health status:', error);
      } finally {
        setHealthLoading(false);
      }
    };

    fetchHealthStatus();
    const interval = setInterval(fetchHealthStatus, 60000);
    return () => clearInterval(interval);
  }, []);

  // Get health check for instance
  const getHealthCheck = (instanceName: string): HealthCheck | undefined => {
    let healthCheck = healthChecks.find(check => check.service_name === instanceName);
    
    if (!healthCheck) {
      const normalizedInstanceName = instanceName
        .toLowerCase()
        .replace(/\s+/g, '-')
        .replace(/[^a-z0-9-]/g, '');
      
      healthCheck = healthChecks.find(check => 
        check.service_name === normalizedInstanceName ||
        check.service_name.includes(normalizedInstanceName) ||
        normalizedInstanceName.includes(check.service_name)
      );
    }
    
    return healthCheck;
  };

  const displayedInstances = showAll ? mcpInstances : mcpInstances.slice(0, 6);

  // Enhanced List Item Component
  const renderInstanceCard = (instance: MCPInstance) => {
    const healthCheck = getHealthCheck(instance.name);
    const statusInfo = getStatusDisplay(instance.status, healthCheck);
    const StatusIcon = statusInfo.icon;
    const urlInfo = getUrlInfo(instance, healthCheck);
    const IconComponent = getCategoryIcon(instance);

    return (
      <div 
        key={instance.id} 
        className={`group relative p-3 border rounded-lg transition-all duration-200 hover:shadow-md hover:-translate-y-0.5 ${statusInfo.bgColor}`}
      >
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            {/* Compact Icon */}
            <div className="relative">
              <div className="h-8 w-8 rounded-lg bg-white dark:bg-slate-800 border border-white dark:border-slate-700 shadow-sm flex items-center justify-center group-hover:scale-105 transition-transform">
                <IconComponent className="h-4 w-4 text-primary" />
              </div>
              {/* Smaller Status indicator overlay */}
              <div className={`absolute -bottom-0.5 -right-0.5 h-3 w-3 rounded-full border border-white dark:border-slate-800 flex items-center justify-center ${statusInfo.color === 'text-green-500' ? 'bg-green-500' : statusInfo.color === 'text-red-500' ? 'bg-red-500' : statusInfo.color === 'text-amber-500' ? 'bg-amber-500' : 'bg-gray-500'}`}>
                {StatusIcon === Loader2 ? (
                  <Loader2 className="h-1.5 w-1.5 text-white animate-spin" />
                ) : (
                  <div className="h-1.5 w-1.5 bg-white rounded-full" />
                )}
              </div>
            </div>

            {/* Compact Content */}
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5">
                <h3 className="text-sm font-semibold text-slate-900 dark:text-white truncate">
                  {instance.name}
                </h3>
                {healthLoading && !healthCheck && (
                  <Loader2 className="h-2.5 w-2.5 animate-spin text-gray-400" />
                )}
              </div>
              
              <p className="text-xs text-muted-foreground mb-1 line-clamp-1">
                {instance.description || `${getCategory(instance)} server instance`}
              </p>

              <div className="flex items-center gap-2">
                <Badge variant="outline" className="text-xs px-1.5 py-0.5">
                  {getCategory(instance)}
                </Badge>
                <div className="flex items-center gap-1">
                  <StatusIcon className={`h-2.5 w-2.5 ${statusInfo.color} ${StatusIcon === Loader2 ? 'animate-spin' : ''}`} />
                  <span className={`text-xs font-medium ${statusInfo.color}`}>
                    {statusInfo.text}
                  </span>
                  {statusInfo.detail && (
                    <span className="text-xs text-muted-foreground">
                      • {statusInfo.detail}
                    </span>
                  )}
                </div>
              </div>

              {/* Compact URL info */}
              {urlInfo.url && urlInfo.displayText && (
                <div className="flex items-center gap-1 mt-1">
                  <Globe className="h-2.5 w-2.5 text-blue-500" />
                  <span className="text-xs text-blue-600 truncate max-w-32">
                    {urlInfo.displayText}
                  </span>
                  <button
                    onClick={() => copyToClipboard(urlInfo.url!)}
                    className="text-gray-400 hover:text-blue-600 transition-colors"
                    title="Copy URL"
                  >
                    <Copy className="h-2.5 w-2.5" />
                  </button>
                </div>
              )}
            </div>
          </div>

          {/* Compact Actions */}
          <div className="flex items-center gap-1 opacity-60 group-hover:opacity-100 transition-opacity">
            {urlInfo.url && (
              <Button size="sm" variant="outline" asChild className="h-6 w-6 p-0">
                <a href={urlInfo.url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="h-3 w-3" />
                </a>
              </Button>
            )}
            <Button size="sm" variant="outline" asChild className="h-6 w-6 p-0">
              <Link href={`/mcp-servers/${instance.id}/edit`}>
                <Settings className="h-3 w-3" />
              </Link>
            </Button>
            <Button size="sm" variant="outline" className="h-6 w-6 p-0 text-destructive hover:text-destructive">
              <Trash2 className="h-3 w-3" />
            </Button>
          </div>
        </div>
      </div>
    );
  };

  // Enhanced Grid Item Component  
  const renderInstanceGrid = (instance: MCPInstance) => {
    const healthCheck = getHealthCheck(instance.name);
    const statusInfo = getStatusDisplay(instance.status, healthCheck);
    const StatusIcon = statusInfo.icon;
    const urlInfo = getUrlInfo(instance, healthCheck);
    const IconComponent = getCategoryIcon(instance);

    return (
      <Card key={instance.id} className={`group hover:shadow-xl hover:-translate-y-1 transition-all duration-300 border-2 ${statusInfo.bgColor}`}>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between mb-3">
            <div className="h-10 w-10 rounded-xl bg-white dark:bg-slate-800 border-2 border-white dark:border-slate-700 shadow-sm flex items-center justify-center">
              <IconComponent className="h-5 w-5 text-primary" />
            </div>
            
            <div className="flex items-center gap-1">
              <StatusIcon className={`h-4 w-4 ${statusInfo.color} ${StatusIcon === Loader2 ? 'animate-spin' : ''}`} />
              {healthLoading && !healthCheck && (
                <Loader2 className="h-3 w-3 animate-spin text-gray-400" />
              )}
            </div>
          </div>
          
          <div>
            <h3 className="font-semibold mb-1 line-clamp-1">{instance.name}</h3>
            <div className="flex items-center gap-2">
              <Badge variant="outline" className="text-xs">
                {getCategory(instance)}
              </Badge>
              <Badge variant={statusInfo.variant} className="text-xs">
                {statusInfo.text}
              </Badge>
            </div>
          </div>
        </CardHeader>

        <CardContent className="pt-0">
          <p className="text-sm text-muted-foreground mb-3 line-clamp-2">
            {instance.description || `${getCategory(instance)} server instance`}
          </p>

          {statusInfo.detail && (
            <div className="flex items-center gap-2 mb-3">
              <Activity className="h-3 w-3 text-muted-foreground" />
              <span className={`text-xs ${statusInfo.color}`}>
                {statusInfo.detail}
              </span>
            </div>
          )}

          {urlInfo.url && urlInfo.displayText && (
            <div className="flex items-center gap-2 mb-3">
              <Globe className="h-3 w-3 text-blue-500" />
              <span className="text-xs text-blue-600 truncate">
                {urlInfo.displayText}
              </span>
              <button
                onClick={() => copyToClipboard(urlInfo.url!)}
                className="text-gray-400 hover:text-blue-600 transition-colors ml-auto"
              >
                <Copy className="h-3 w-3" />
              </button>
            </div>
          )}

          <div className="flex gap-2">
            {urlInfo.url && (
              <Button size="sm" className="flex-1" asChild>
                <a href={urlInfo.url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="h-4 w-4 mr-1" />
                  Access
                </a>
              </Button>
            )}
            <Button size="sm" variant="outline" asChild>
              <Link href={`/mcp-servers/${instance.id}/edit`}>
                <Settings className="h-4 w-4" />
              </Link>
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  };

  // Compact Empty State
  if (mcpInstances.length === 0) {
    return (
      <div className="space-y-4">
        <div className="flex items-center gap-2">
          <div className="h-6 w-6 rounded-lg bg-gradient-to-br from-slate-200 to-slate-300 dark:from-slate-700 dark:to-slate-600 flex items-center justify-center">
            <Activity className="h-3 w-3 text-slate-600 dark:text-slate-300" />
          </div>
          <div>
            <h2 className="text-lg font-bold">My Active Servers</h2>
            <p className="text-xs text-muted-foreground">No servers configured yet</p>
          </div>
        </div>
        
        <Card className="border-dashed border border-slate-200 dark:border-slate-700">
          <CardContent className="py-8 text-center">
            <div className="max-w-md mx-auto space-y-3">
              <div className="h-12 w-12 mx-auto rounded-xl bg-gradient-to-br from-slate-100 to-slate-200 dark:from-slate-800 dark:to-slate-700 flex items-center justify-center">
                <Zap className="h-6 w-6 text-slate-400" />
              </div>
              <div>
                <h3 className="text-base font-semibold mb-1">Ready to connect your first server?</h3>
                <p className="text-xs text-muted-foreground mb-4">
                  MCP servers provide tools and context to your AI agents. Get started with our quick actions above.
                </p>
              </div>
              <div className="flex gap-2 justify-center">
                <Button size="sm" asChild>
                  <Link href="/mcp-servers/add">
                    <Globe className="h-3 w-3 mr-1" />
                    Connect by URL
                  </Link>
                </Button>
                <Button size="sm" variant="outline" asChild>
                  <Link href="/mcp-servers/marketplace">
                    <Wrench className="h-3 w-3 mr-1" />
                    Browse Templates
                  </Link>
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="space-y-4">
      {/* Compact Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <div className="h-6 w-6 rounded-lg bg-gradient-to-br from-green-500 to-emerald-500 flex items-center justify-center">
            <Activity className="h-3 w-3 text-white" />
          </div>
          <div>
            <h2 className="text-lg font-bold">My Active Servers</h2>
            <p className="text-xs text-muted-foreground">
              {mcpInstances.length} {mcpInstances.length === 1 ? 'server' : 'servers'} configured
            </p>
          </div>
        </div>
        
        <div className="flex items-center gap-1">
          <Button 
            variant={viewMode === 'list' ? 'default' : 'outline'} 
            size="sm"
            onClick={() => setViewMode('list')}
            className="h-7 w-7 p-0"
          >
            <List className="h-3 w-3" />
          </Button>
          <Button 
            variant={viewMode === 'grid' ? 'default' : 'outline'} 
            size="sm"
            onClick={() => setViewMode('grid')}
            className="h-7 w-7 p-0"
          >
            <Grid className="h-3 w-3" />
          </Button>
          <Button variant="outline" size="sm" asChild className="h-7 text-xs">
            <Link href="/mcp-servers/tools">
              <Settings className="h-3 w-3 mr-1" />
              Manage
            </Link>
          </Button>
        </div>
      </div>
      
      {/* Loading Skeletons */}
      {healthLoading && mcpInstances.length > 0 && (
        <div className="space-y-4">
          <div className="flex items-center gap-2 text-sm text-muted-foreground mb-4">
            <Loader2 className="h-4 w-4 animate-spin" />
            <span>Checking server health...</span>
          </div>
          
          {/* Skeleton loading cards */}
          <div className={viewMode === 'grid' ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6" : "space-y-4"}>
            {Array.from({ length: Math.min(3, mcpInstances.length) }).map((_, i) => (
              <div key={i} className={viewMode === 'grid' ? "p-4 border-2 rounded-xl space-y-3" : "p-4 border-2 rounded-xl"}>
                <div className="flex items-center gap-4">
                  <Skeleton className="h-12 w-12 rounded-xl" />
                  <div className="flex-1 space-y-2">
                    <Skeleton className="h-4 w-32" />
                    <Skeleton className="h-3 w-48" />
                    <div className="flex gap-2">
                      <Skeleton className="h-5 w-16" />
                      <Skeleton className="h-5 w-20" />
                    </div>
                  </div>
                  {viewMode === 'list' && (
                    <div className="flex gap-2">
                      <Skeleton className="h-8 w-8" />
                      <Skeleton className="h-8 w-8" />
                      <Skeleton className="h-8 w-8" />
                    </div>
                  )}
                </div>
                {viewMode === 'grid' && (
                  <div className="space-y-2">
                    <Skeleton className="h-3 w-full" />
                    <Skeleton className="h-8 w-full" />
                  </div>
                )}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Compact Instances Display */}
      <div className={viewMode === 'grid' ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3" : "space-y-2"}>
        {displayedInstances.map(instance => 
          viewMode === 'grid' ? renderInstanceGrid(instance) : renderInstanceCard(instance)
        )}
      </div>
      
      {/* Compact Show More/Less */}
      {mcpInstances.length > 6 && (
        <div className="text-center">
          <Button 
            variant="outline" 
            size="sm"
            onClick={() => setShowAll(!showAll)}
            className="text-xs h-7"
          >
            {showAll ? (
              <>Show fewer</>
            ) : (
              <>
                <Clock className="h-3 w-3 mr-1" />
                Show {mcpInstances.length - 6} more
              </>
            )}
          </Button>
        </div>
      )}
    </div>
  );
}