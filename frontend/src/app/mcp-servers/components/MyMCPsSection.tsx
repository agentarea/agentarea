"use client";

import { useState, useEffect } from "react";
import { Card, CardContent, CardHeader } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { CheckCircle, AlertCircle, Settings, Trash2, ExternalLink, Grid, List, AlertTriangle, Loader2 } from "lucide-react";
import Link from "next/link";
import { getMCPHealthStatus } from "@/lib/api";

interface MCPInstance {
  id: string;
  name: string;
  description?: string;
  status: string;
  endpoint_url?: string;
  created_at: string;
  server_spec_id?: string;
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
  if (name.includes('filesystem') || name.includes('file')) return '📁';
  if (name.includes('memory') || name.includes('knowledge')) return '🧠';
  if (name.includes('git') || name.includes('github')) return '🐙';
  if (name.includes('web') || name.includes('fetch') || name.includes('browser')) return '🌐';
  if (name.includes('database') || name.includes('sql')) return '📊';
  if (name.includes('slack') || name.includes('gmail') || name.includes('message')) return '💬';
  if (name.includes('puppeteer') || name.includes('automation')) return '🤖';
  return '🔧';
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

// Helper function to get status display with health information
const getStatusDisplay = (status: string, healthCheck?: HealthCheck) => {
  // If we have health information, use it to determine actual status
  if (healthCheck) {
    if (healthCheck.container_status === 'running' && healthCheck.healthy) {
      return { 
        text: 'Healthy', 
        variant: 'default' as const, 
        icon: CheckCircle, 
        color: 'text-green-500',
        detail: `${healthCheck.response_time_ms}ms`
      };
    } else if (healthCheck.container_status === 'running' && !healthCheck.healthy) {
      return { 
        text: 'Unhealthy', 
        variant: 'destructive' as const, 
        icon: AlertTriangle, 
        color: 'text-red-500',
        detail: healthCheck.error || 'Health check failed'
      };
    } else if (healthCheck.container_status === 'stopped') {
      return { 
        text: 'Stopped', 
        variant: 'secondary' as const, 
        icon: AlertCircle, 
        color: 'text-gray-500',
        detail: 'Container not running'
      };
    }
  }
  
  // Fallback to original status logic
  switch (status) {
    case 'running':
      return { text: 'Available', variant: 'default' as const, icon: CheckCircle, color: 'text-green-500' };
    case 'stopped':
      return { text: 'Stopped', variant: 'secondary' as const, icon: AlertCircle, color: 'text-red-500' };
    case 'pending':
      return { text: 'Starting', variant: 'secondary' as const, icon: Loader2, color: 'text-amber-500' };
    default:
      return { text: 'Needs Setup', variant: 'outline' as const, icon: AlertCircle, color: 'text-amber-500' };
  }
};

export function MyMCPsSection({ mcpInstances }: MyMCPsSectionProps) {
  const [viewMode, setViewMode] = useState<'grid' | 'list'>('list');
  const [showAll, setShowAll] = useState(false);
  const [healthChecks, setHealthChecks] = useState<HealthCheck[]>([]);
  const [healthLoading, setHealthLoading] = useState(true);

  // Fetch health status on component mount and set up polling
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

    // Initial fetch
    fetchHealthStatus();

    // Set up polling every 30 seconds
    const interval = setInterval(fetchHealthStatus, 30000);

    return () => clearInterval(interval);
  }, []);

  // Helper function to get health check for an instance
  const getHealthCheck = (instanceName: string): HealthCheck | undefined => {
    return healthChecks.find(check => check.service_name === instanceName);
  };

  const displayedInstances = showAll ? mcpInstances : mcpInstances.slice(0, 3);

  const renderInstanceCard = (instance: MCPInstance) => {
    const healthCheck = getHealthCheck(instance.name);
    const statusInfo = getStatusDisplay(instance.status, healthCheck);
    const StatusIcon = statusInfo.icon;

    return (
      <div key={instance.id} className="flex items-center justify-between p-3 border rounded-lg hover:bg-secondary/50 transition-colors">
        <div className="flex items-center gap-3">
          <div className="h-10 w-10 rounded-lg bg-primary/10 flex items-center justify-center">
            {getCategoryIcon(instance)}
          </div>
          <div>
            <div className="flex items-center gap-2">
              <h3 className="font-medium">{instance.name}</h3>
              <StatusIcon className={`h-4 w-4 ${statusInfo.color} ${StatusIcon === Loader2 ? 'animate-spin' : ''}`} />
              {healthLoading && !healthCheck && <Loader2 className="h-3 w-3 animate-spin text-gray-400" />}
            </div>
            <p className="text-sm text-muted-foreground">
              {instance.description || `${getCategory(instance)} instance`}
            </p>
            {/* Show health details if available */}
            {healthCheck && statusInfo.detail && (
              <p className={`text-xs ${healthCheck.healthy ? 'text-green-600' : 'text-red-600'}`}>
                {statusInfo.detail}
              </p>
            )}
            {/* Show endpoint URL (prefer health check URL over instance URL) */}
            {(healthCheck?.url || instance.endpoint_url) && (
              <p className="text-xs text-blue-600 truncate max-w-xs">
                🔗 {healthCheck?.url || instance.endpoint_url}
              </p>
            )}
            <div className="flex flex-wrap gap-1 mt-1">
              <Badge variant="outline" className="text-xs">
                {getCategory(instance)}
              </Badge>
              <Badge variant={statusInfo.variant} className="text-xs">
                {statusInfo.text}
              </Badge>
              {healthCheck?.healthy && healthCheck.http_reachable && (
                <Badge variant="outline" className="text-xs">
                  🌐 Reachable
                </Badge>
              )}
              {healthCheck && !healthCheck.healthy && (
                <Badge variant="destructive" className="text-xs">
                  ⚠️ Warning
                </Badge>
              )}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2">
          {(healthCheck?.url || instance.endpoint_url) && healthCheck?.healthy && (
            <Button size="sm" variant="outline" asChild>
              <a href={healthCheck?.url || instance.endpoint_url} target="_blank" rel="noopener noreferrer">
                <ExternalLink className="h-4 w-4 mr-1" />
                Access
              </a>
            </Button>
          )}
          <Button size="sm" variant="outline" asChild>
            <Link href={`/mcp-servers/${instance.id}/edit`}>
              <Settings className="h-4 w-4 mr-1" />
              Configure
            </Link>
          </Button>
          <Button size="sm" variant="outline" className="text-destructive hover:text-destructive">
            <Trash2 className="h-4 w-4" />
          </Button>
        </div>
      </div>
    );
  };

  const renderInstanceGrid = (instance: MCPInstance) => {
    const healthCheck = getHealthCheck(instance.name);
    const statusInfo = getStatusDisplay(instance.status, healthCheck);
    const StatusIcon = statusInfo.icon;

    return (
      <Card key={instance.id} className="hover:shadow-md transition-shadow">
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <div className="h-8 w-8 rounded-lg bg-primary/10 flex items-center justify-center">
                {getCategoryIcon(instance)}
              </div>
              <div>
                <h3 className="font-medium">{instance.name}</h3>
                <div className="flex items-center gap-1 mt-1">
                  <Badge variant="secondary" className="text-xs">
                    {getCategory(instance)}
                  </Badge>
                  <StatusIcon className={`h-3 w-3 ${statusInfo.color} ${StatusIcon === Loader2 ? 'animate-spin' : ''}`} />
                  {healthLoading && !healthCheck && <Loader2 className="h-3 w-3 animate-spin text-gray-400" />}
                </div>
              </div>
            </div>
            <Badge variant={statusInfo.variant} className="text-xs">
              {statusInfo.text}
            </Badge>
          </div>
        </CardHeader>
        <CardContent className="pt-0">
          <p className="text-sm text-muted-foreground mb-3">
            {instance.description || `${getCategory(instance)} instance`}
          </p>
          {/* Show health details if available */}
          {healthCheck && statusInfo.detail && (
            <p className={`text-xs mb-2 ${healthCheck.healthy ? 'text-green-600' : 'text-red-600'}`}>
              {statusInfo.detail}
            </p>
          )}
          {/* Show endpoint URL (prefer health check URL over instance URL) */}
          {(healthCheck?.url || instance.endpoint_url) && (
            <p className="text-xs text-blue-600 truncate mb-2">
              🔗 {healthCheck?.url || instance.endpoint_url}
            </p>
          )}
          <div className="flex flex-wrap gap-1 mb-3">
            <Badge variant="outline" className="text-xs">
              {getCategory(instance)}
            </Badge>
            {healthCheck?.healthy && healthCheck.http_reachable && (
              <Badge variant="outline" className="text-xs">
                🌐 Reachable
              </Badge>
            )}
            {healthCheck && !healthCheck.healthy && (
              <Badge variant="destructive" className="text-xs">
                ⚠️ Warning
              </Badge>
            )}
          </div>
          <div className="flex gap-2">
            {(healthCheck?.url || instance.endpoint_url) && healthCheck?.healthy && (
              <Button size="sm" className="flex-1" asChild>
                <a href={healthCheck?.url || instance.endpoint_url} target="_blank" rel="noopener noreferrer">
                  <ExternalLink className="h-4 w-4 mr-1" />
                  Access
                </a>
              </Button>
            )}
            <Button size="sm" className="flex-1" asChild>
              <Link href={`/mcp-servers/${instance.id}/edit`}>
                <Settings className="h-4 w-4 mr-1" />
                Configure
              </Link>
            </Button>
            <Button size="sm" variant="outline" className="text-destructive hover:text-destructive">
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        </CardContent>
      </Card>
    );
  };

  if (mcpInstances.length === 0) {
    return (
      <div className="mb-6">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold">📋 My MCPs (0)</h2>
          <Button variant="outline" size="sm" asChild>
            <Link href="/mcp-servers/manage">📋 Manage All</Link>
          </Button>
        </div>
        
        <Card>
          <CardContent className="py-12 text-center">
            <div className="text-muted-foreground mb-4">
              <Settings className="h-12 w-12 mx-auto mb-4 opacity-50" />
              <h3 className="text-lg font-semibold mb-2">No MCPs configured</h3>
              <p>Get started by creating your first MCP instance using the actions above.</p>
            </div>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="mb-6">
      <div className="flex items-center justify-between mb-4">
        <h2 className="text-lg font-semibold">📋 My MCPs ({mcpInstances.length})</h2>
        <div className="flex gap-2">
          <Button 
            variant={viewMode === 'grid' ? 'default' : 'outline'} 
            size="sm"
            onClick={() => setViewMode('grid')}
          >
            <Grid className="h-4 w-4" />
          </Button>
          <Button 
            variant={viewMode === 'list' ? 'default' : 'outline'} 
            size="sm"
            onClick={() => setViewMode('list')}
          >
            <List className="h-4 w-4" />
          </Button>
          <Button variant="outline" size="sm" asChild>
            <Link href="/mcp-servers/manage">📋 Manage All</Link>
          </Button>
        </div>
      </div>
      
      <Card>
        <CardContent className="p-4">
          <div className={viewMode === 'grid' ? "grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4" : "space-y-3"}>
            {displayedInstances.map(instance => 
              viewMode === 'grid' ? renderInstanceGrid(instance) : renderInstanceCard(instance)
            )}
          </div>
          
          {mcpInstances.length > 3 && !showAll && (
            <div className="mt-4 text-center">
              <Button 
                variant="outline" 
                size="sm" 
                onClick={() => setShowAll(true)}
              >
                Show {mcpInstances.length - 3} more instances
              </Button>
            </div>
          )}
          
          {showAll && mcpInstances.length > 3 && (
            <div className="mt-4 text-center">
              <Button 
                variant="outline" 
                size="sm" 
                onClick={() => setShowAll(false)}
              >
                Show fewer
              </Button>
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
} 