"use client";

import React, { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { Card } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Settings,
  RefreshCw,
  Users,
  Building2,
  Shield,
  Plus,
  Trash2,
  ChevronRight,
  ChevronDown,
  ChevronLeft,
  Database,
  AlertTriangle,
  CheckCircle2,
  Clock
} from "lucide-react";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { 
  mockPermissions,
  accessColors,
  type Permission
} from "../_mocks/data";
import { sourcesApi, SourceResponse } from '@/api/sources';
import { LoadingSpinner } from '@/components/LoadingSpinner';
import { SourceStatus, SourceType } from '@/types/source';
import { cn } from "@/lib/utils";

// Enhanced Permission Node component with better accessibility
const PermissionNode = ({ permission, depth = 0 }: { permission: Permission; depth?: number }) => {
  const [isExpanded, setIsExpanded] = React.useState(true);
  const hasChildren = permission.children && permission.children.length > 0;
  
  return (
    <>
      <TableRow className="hover:bg-secondary/40 transition-colors">
        <TableCell className="py-3">
          <div className="flex items-center gap-2" style={{ paddingLeft: `${depth * 24}px` }}>
            {hasChildren && (
              <button 
                onClick={() => setIsExpanded(!isExpanded)}
                className="p-1 hover:bg-secondary rounded-full transition-colors"
                aria-label={isExpanded ? "Collapse" : "Expand"}
                aria-expanded={isExpanded}
              >
                {isExpanded ? (
                  <ChevronDown className="h-4 w-4" aria-hidden="true" />
                ) : (
                  <ChevronRight className="h-4 w-4" aria-hidden="true" />
                )}
              </button>
            )}
            {!hasChildren && <div className="w-6" />}
            <div className="bg-secondary/30 p-1.5 rounded-full">
              {permission.type === "user" && <Users className="h-4 w-4" aria-hidden="true" />}
              {permission.type === "team" && <Users className="h-4 w-4" aria-hidden="true" />}
              {permission.type === "organization" && <Building2 className="h-4 w-4" aria-hidden="true" />}
            </div>
            <span className="font-medium">{permission.name}</span>
          </div>
        </TableCell>
        <TableCell className="capitalize text-muted-foreground">{permission.type}</TableCell>
        <TableCell>
          <Badge className={`${accessColors[permission.access]} rounded-full px-3`}>
            {permission.access.toUpperCase()}
          </Badge>
        </TableCell>
        <TableCell>
          <div className="flex flex-wrap gap-1.5">
            {permission.scope.resources.map((resource: string) => (
              <Badge key={resource} variant="outline" className="rounded-full bg-background/50 border-dashed">
                {resource}
              </Badge>
            ))}
          </div>
        </TableCell>
        <TableCell className="text-muted-foreground">{permission.grantedBy}</TableCell>
        <TableCell className="text-muted-foreground">{permission.grantedAt}</TableCell>
        <TableCell>
          <div className="flex items-center gap-2">
            <Button 
              variant="ghost" 
              size="icon" 
              className="rounded-full hover:bg-secondary/80"
              aria-label="Edit permissions"
            >
              <Shield className="h-4 w-4" aria-hidden="true" />
            </Button>
            <Button 
              variant="ghost" 
              size="icon" 
              className="rounded-full hover:bg-red-500/10 text-red-600"
              aria-label="Delete permission"
            >
              <Trash2 className="h-4 w-4" aria-hidden="true" />
            </Button>
          </div>
        </TableCell>
      </TableRow>
      {hasChildren && isExpanded && permission.children?.map((child: Permission) => (
        <PermissionNode key={child.id} permission={child} depth={depth + 1} />
      ))}
    </>
  );
};

interface Props {
  params: Promise<{
    sourceId: string;
  }>;
}

// Enhanced source details component with improved UI/UX
export default function SourceDetails({ params }: Props) {
  const router = useRouter();
  const unwrappedParams = React.use(params) as { sourceId: string };
  const sourceId = unwrappedParams.sourceId;
  const [source, setSource] = useState<SourceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [isConfirmingDelete, setIsConfirmingDelete] = useState(false);

  useEffect(() => {
    loadSource();
  }, [sourceId]);

  async function loadSource() {
    try {
      const data = await sourcesApi.getSource(sourceId);
      setSource(data);
    } catch (err) {
      setError('Failed to load source');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  async function handleStatusUpdate(status: SourceStatus) {
    if (!source) return;

    try {
      setLoading(true);
      const updated = await sourcesApi.updateSource(source.source_id, { status });
      setSource(updated);
    } catch (err) {
      setError('Failed to update status');
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  async function handleDelete() {
    if (!source) return;

    if (!isConfirmingDelete) {
      setIsConfirmingDelete(true);
      return;
    }

    try {
      setLoading(true);
      await sourcesApi.deleteSource(source.source_id);
      router.push('/sources/browse');
    } catch (err) {
      setError('Failed to delete source');
      console.error(err);
    } finally {
      setLoading(false);
      setIsConfirmingDelete(false);
    }
  }

  // Helper function to get status icon
  const getStatusIcon = (status: SourceStatus) => {
    switch (status) {
      case SourceStatus.ACTIVE:
        return <CheckCircle2 className="h-4 w-4 mr-1" aria-hidden="true" />;
      case SourceStatus.INACTIVE:
        return <Clock className="h-4 w-4 mr-1" aria-hidden="true" />;
      case SourceStatus.ERROR:
        return <AlertTriangle className="h-4 w-4 mr-1" aria-hidden="true" />;
      default:
        return null;
    }
  };

  // Helper function to get status color class
  const getStatusColorClass = (status: SourceStatus) => {
    switch (status) {
      case SourceStatus.ACTIVE:
        return "text-green-500 bg-green-50";
      case SourceStatus.INACTIVE:
        return "text-yellow-500 bg-yellow-50";
      case SourceStatus.ERROR:
        return "text-red-500 bg-red-50";
      default:
        return "text-blue-500 bg-blue-50";
    }
  };

  // Helper function to get type color class
  const getTypeColorClass = (type: SourceType) => {
    switch (type) {
      case SourceType.DATABASE:
        return "bg-emerald-100 text-emerald-700";
      case SourceType.API:
        return "bg-blue-100 text-blue-700";
      case SourceType.FILE:
        return "bg-indigo-100 text-indigo-700";
      case SourceType.STREAM:
        return "bg-purple-100 text-purple-700";
      default:
        return "bg-gray-100 text-gray-700";
    }
  };

  if (loading) return (
    <div className="flex items-center justify-center h-screen">
      <LoadingSpinner />
    </div>
  );
  
  if (error) return (
    <div className="p-8 flex flex-col items-center justify-center h-[50vh]">
      <AlertTriangle className="h-12 w-12 text-red-500 mb-4" aria-hidden="true" />
      <h2 className="text-xl font-semibold mb-2">Error Loading Source</h2>
      <p className="text-red-500 mb-4">{error}</p>
      <Button onClick={() => router.push('/sources/browse')}>
        Return to Sources
      </Button>
    </div>
  );
  
  if (!source) return (
    <div className="p-8 flex flex-col items-center justify-center h-[50vh]">
      <AlertTriangle className="h-12 w-12 text-yellow-500 mb-4" aria-hidden="true" />
      <h2 className="text-xl font-semibold mb-2">Source Not Found</h2>
      <p className="text-muted-foreground mb-4">The requested source could not be found.</p>
      <Button onClick={() => router.push('/sources/browse')}>
        Return to Sources
      </Button>
    </div>
  );

  return (
    <div className="p-4 md:p-8 max-w-7xl mx-auto">
      {/* Breadcrumb navigation */}
      <nav aria-label="Breadcrumb" className="flex items-center gap-2 mb-6 text-sm">
        <Button 
          variant="ghost" 
          className="gap-2 h-8 hover:bg-secondary" 
          onClick={() => router.push('/sources/browse')}
        >
          <ChevronLeft className="h-4 w-4" aria-hidden="true" />
          <span>Sources</span>
        </Button>
        <ChevronRight className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
        <span className="text-muted-foreground">{source.name}</span>
      </nav>

      {/* Source header */}
      <div className="flex flex-col md:flex-row justify-between items-start gap-4 mb-8">
        <div>
          <div className="flex items-center gap-4 mb-4">
            <div className={cn("h-16 w-16 rounded-lg flex items-center justify-center", getTypeColorClass(source.type))}>
              <Database className="h-8 w-8" aria-hidden="true" />
            </div>
            <div>
              <div className="flex items-center gap-2 flex-wrap">
                <h1 className="text-2xl md:text-3xl font-bold">{source.name}</h1>
              </div>
              <div className="flex items-center gap-2 mt-1 flex-wrap">
                <span className={cn("text-sm px-2 py-1 rounded-full", getTypeColorClass(source.type))}>
                  {source.type}
                </span>
                <span className="text-sm text-muted-foreground">•</span>
                <div className={cn("flex items-center gap-1 px-2 py-1 rounded-full", getStatusColorClass(source.status))}>
                  {getStatusIcon(source.status)}
                  <span className="text-sm capitalize">{source.status.replace('_', ' ')}</span>
                </div>
              </div>
            </div>
          </div>
          <p className="text-lg text-muted-foreground">{source.description}</p>
        </div>
        <div className="flex flex-wrap gap-2 mt-2 md:mt-0">
          <Button 
            variant="outline" 
            className="flex items-center gap-2"
            onClick={() => loadSource()}
          >
            <RefreshCw className="h-4 w-4" aria-hidden="true" />
            <span>Refresh</span>
          </Button>
          <Button 
            variant="outline" 
            className="flex items-center gap-2"
          >
            <Settings className="h-4 w-4" aria-hidden="true" />
            <span>Settings</span>
          </Button>
        </div>
      </div>

      {/* Main content tabs */}
      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList className="bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 overflow-x-auto flex w-full">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="permissions">Permissions</TabsTrigger>
          <TabsTrigger value="resources">Resources</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            {/* Source Information Card */}
            <Card className="backdrop-blur-sm bg-card/50 border-black/5 shadow-sm hover:shadow-md transition-all duration-200">
              <div className="p-6">
                <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                  <div className="p-2 rounded-full bg-primary/10">
                    <Building2 className="h-5 w-5 text-primary" aria-hidden="true" />
                  </div>
                  <span>Source Information</span>
                </h3>
                <div className="space-y-4">
                  <div>
                    <p className="text-sm text-muted-foreground">Organization</p>
                    <div className="flex items-center gap-2 mt-1">
                      <Building2 className="h-4 w-4 text-muted-foreground" aria-hidden="true" />
                      <span className="font-medium">{source.metadata?.organization || "Not specified"}</span>
                    </div>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Owner</p>
                    <span className="capitalize font-medium">{source.owner}</span>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Created</p>
                    <span className="font-medium">{new Date(source.created_at).toLocaleDateString()}</span>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Last Updated</p>
                    <span className="font-medium">{new Date(source.updated_at).toLocaleDateString()}</span>
                  </div>
                </div>
              </div>
            </Card>

            {/* Sync Status Card */}
            <Card className="backdrop-blur-sm bg-card/50 border-black/5 shadow-sm hover:shadow-md transition-all duration-200">
              <div className="p-6">
                <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                  <div className="p-2 rounded-full bg-primary/10">
                    <RefreshCw className="h-5 w-5 text-primary" aria-hidden="true" />
                  </div>
                  <span>Status Information</span>
                </h3>
                <div className="space-y-4">
                  <div>
                    <p className="text-sm text-muted-foreground">Current Status</p>
                    <div className={cn("inline-flex items-center gap-1 px-3 py-1 rounded-full mt-1", getStatusColorClass(source.status))}>
                      {getStatusIcon(source.status)}
                      <span className="font-medium capitalize">{source.status}</span>
                    </div>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Last Sync</p>
                    <span className="font-medium">{source.metadata?.lastSync || "Never"}</span>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Data Points</p>
                    <span className="font-medium">{source.metadata?.dataPoints || "Unknown"}</span>
                  </div>
                </div>
              </div>
            </Card>

            {/* Configuration Card */}
            <Card className="backdrop-blur-sm bg-card/50 border-black/5 shadow-sm hover:shadow-md transition-all duration-200 md:col-span-2">
              <div className="p-6">
                <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                  <div className="p-2 rounded-full bg-primary/10">
                    <Database className="h-5 w-5 text-primary" aria-hidden="true" />
                  </div>
                  <span>Configuration</span>
                </h3>
                <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                  {Object.entries(source.configuration || {}).map(([key, value]) => (
                    <div key={key}>
                      <p className="text-sm text-muted-foreground capitalize">{key.replace(/_/g, ' ')}</p>
                      <span className="font-medium break-words">
                        {typeof value === 'object' ? JSON.stringify(value) : String(value)}
                      </span>
                    </div>
                  ))}
                  {Object.keys(source.configuration || {}).length === 0 && (
                    <p className="text-muted-foreground col-span-2">No configuration available</p>
                  )}
                </div>
              </div>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="permissions">
          <Card className="backdrop-blur-sm bg-card/50 border-black/5">
            <div className="p-6 border-b border-black/5">
              <div className="flex flex-col sm:flex-row justify-between items-start sm:items-center gap-4">
                <div>
                  <h3 className="text-lg font-semibold">Access Control</h3>
                  <p className="text-sm text-muted-foreground">Manage who has access to this source</p>
                </div>
                <Button className="flex items-center gap-2 rounded-full">
                  <Plus className="h-4 w-4" aria-hidden="true" />
                  <span>Add Permission</span>
                </Button>
              </div>
            </div>
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow className="hover:bg-transparent">
                    <TableHead className="font-semibold">Name</TableHead>
                    <TableHead className="font-semibold">Type</TableHead>
                    <TableHead className="font-semibold">Access Level</TableHead>
                    <TableHead className="font-semibold">Resources</TableHead>
                    <TableHead className="font-semibold">Granted By</TableHead>
                    <TableHead className="font-semibold">Granted At</TableHead>
                    <TableHead className="font-semibold">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {mockPermissions
                    .filter(p => p.parentId === null)
                    .map((permission) => (
                      <PermissionNode key={permission.id} permission={permission} />
                    ))}
                </TableBody>
              </Table>
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="resources">
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">Resource Management</h3>
            <p className="text-muted-foreground mb-4">Configure and manage available resources from this source</p>
            
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4 mt-6">
              {(source.metadata?.resourceTypes as string[] || []).map((resourceType, index) => (
                <Card key={index} className="p-4 hover:shadow-md transition-all">
                  <h4 className="font-medium mb-2 capitalize">{resourceType}</h4>
                  <div className="flex justify-between">
                    <Badge variant="outline">Available</Badge>
                    <Button variant="ghost" size="sm">Configure</Button>
                  </div>
                </Card>
              ))}
              {(!source.metadata?.resourceTypes || (source.metadata?.resourceTypes as string[]).length === 0) && (
                <div className="col-span-3 flex flex-col items-center justify-center p-8 border border-dashed rounded-lg">
                  <Database className="h-12 w-12 text-muted-foreground mb-4" aria-hidden="true" />
                  <h4 className="text-lg font-medium mb-2">No Resources Available</h4>
                  <p className="text-muted-foreground text-center mb-4">This source does not have any resources configured yet.</p>
                  <Button>Add Resource</Button>
                </div>
              )}
            </div>
          </Card>
        </TabsContent>

        <TabsContent value="settings">
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">Source Settings</h3>
            <p className="text-muted-foreground mb-6">Configure source settings and preferences</p>
            
            <div className="space-y-6">
              <div>
                <h4 className="text-md font-medium mb-2">Status Management</h4>
                <div className="flex flex-wrap gap-2">
                  <Button
                    onClick={() => handleStatusUpdate(SourceStatus.ACTIVE)}
                    className="bg-green-500 hover:bg-green-600 text-white"
                    disabled={source.status === SourceStatus.ACTIVE}
                  >
                    <CheckCircle2 className="h-4 w-4 mr-2" aria-hidden="true" />
                    Activate
                  </Button>
                  <Button
                    onClick={() => handleStatusUpdate(SourceStatus.INACTIVE)}
                    className="bg-yellow-500 hover:bg-yellow-600 text-white"
                    disabled={source.status === SourceStatus.INACTIVE}
                  >
                    <Clock className="h-4 w-4 mr-2" aria-hidden="true" />
                    Deactivate
                  </Button>
                </div>
              </div>
              
              <div className="border-t pt-6">
                <h4 className="text-md font-medium mb-2 text-red-600">Danger Zone</h4>
                <p className="text-sm text-muted-foreground mb-4">
                  Permanently delete this source and all of its data. This action cannot be undone.
                </p>
                <Button
                  onClick={handleDelete}
                  className={cn(
                    "bg-red-500 hover:bg-red-600 text-white",
                    isConfirmingDelete && "animate-pulse"
                  )}
                >
                  <Trash2 className="h-4 w-4 mr-2" aria-hidden="true" />
                  {isConfirmingDelete ? "Confirm Delete" : "Delete Source"}
                </Button>
              </div>
            </div>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  );
} 