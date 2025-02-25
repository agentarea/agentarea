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
  Lock,
  Users,
  Building2,
  Shield,
  Globe,
  Plus,
  Trash2,
  ChevronRight,
  ChevronDown,
  ChevronLeft,
  Database
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
  mockDataSources,
  mockPermissions,
  statusColors,
  accessColors,
  typeColors,
  type Permission
} from "../_mocks/data";
import { sourcesApi, SourceResponse, SourceUpdate } from '@/api/sources';
import { LoadingSpinner } from '@/components/LoadingSpinner';
import { SourceStatus } from '@/types/source';

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
              >
                {isExpanded ? (
                  <ChevronDown className="h-4 w-4" />
                ) : (
                  <ChevronRight className="h-4 w-4" />
                )}
              </button>
            )}
            {!hasChildren && <div className="w-6" />}
            <div className="bg-secondary/30 p-1.5 rounded-full">
              {permission.type === "user" && <Users className="h-4 w-4" />}
              {permission.type === "team" && <Users className="h-4 w-4" />}
              {permission.type === "organization" && <Building2 className="h-4 w-4" />}
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
            <Button variant="ghost" size="icon" className="rounded-full hover:bg-secondary/80">
              <Shield className="h-4 w-4" />
            </Button>
            <Button variant="ghost" size="icon" className="rounded-full hover:bg-red-500/10 text-red-600">
              <Trash2 className="h-4 w-4" />
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

export default function SourceDetails({ params }: Props) {
  const router = useRouter();
  const unwrappedParams = React.use(params) as { sourceId: string };
  const sourceId = unwrappedParams.sourceId;
  const [source, setSource] = useState<SourceResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
      const updated = await sourcesApi.updateSource(source.source_id, { status });
      setSource(updated);
    } catch (err) {
      setError('Failed to update status');
      console.error(err);
    }
  }

  async function handleDelete() {
    if (!source || !confirm('Are you sure you want to delete this source?')) return;

    try {
      await sourcesApi.deleteSource(source.source_id);
      router.push('/sources/browse');
    } catch (err) {
      setError('Failed to delete source');
      console.error(err);
    }
  }

  if (loading) return <LoadingSpinner />;
  if (error) return <div className="text-red-500">{error}</div>;
  if (!source) return <div>Source not found</div>;

  return (
    <div className="p-8">
      <div className="flex items-center gap-2 mb-6 text-sm">
        <Button 
          variant="ghost" 
          className="gap-2 h-8 hover:bg-secondary" 
          onClick={() => router.push('/sources/browse')}
        >
          <ChevronLeft className="h-4 w-4" />
          Sources
        </Button>
        <ChevronRight className="h-4 w-4 text-muted-foreground" />
        <span className="text-muted-foreground">{source.name}</span>
      </div>

      <div className="flex justify-between items-start mb-8">
        <div>
          <div className="flex items-center gap-4 mb-4">
            <div className={`h-16 w-16 rounded-lg flex items-center justify-center ${typeColors[source.type]}`}>
              {source.icon}
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h1 className="text-3xl font-bold">{source.name}</h1>
                {source.visibility === "private" && (
                  <Lock className="h-5 w-5 text-muted-foreground" />
                )}
              </div>
              <div className="flex items-center gap-2 mt-1">
                <span className={`text-sm px-2 py-1 rounded-full ${typeColors[source.type]}`}>
                  {source.type}
                </span>
                <span className="text-sm text-muted-foreground">•</span>
                <div className={`flex items-center gap-1 px-2 py-1 rounded-full ${statusColors[source.status]}`}>
                  {source.status === "connected" ? "✔" : source.status === "disconnected" ? "✗" : "⟳"}
                  <span className="text-sm capitalize">{source.status.replace('_', ' ')}</span>
                </div>
              </div>
            </div>
          </div>
          <p className="text-lg text-muted-foreground">{source.description}</p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline" className="flex items-center gap-2">
            <RefreshCw className="h-4 w-4" />
            Sync Now
          </Button>
          <Button variant="outline" className="flex items-center gap-2">
            <Settings className="h-4 w-4" />
            Settings
          </Button>
        </div>
      </div>

      <Tabs defaultValue="overview" className="space-y-4">
        <TabsList className="bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
          <TabsTrigger value="overview">Overview</TabsTrigger>
          <TabsTrigger value="permissions">Permissions</TabsTrigger>
          <TabsTrigger value="resources">Resources</TabsTrigger>
          <TabsTrigger value="settings">Settings</TabsTrigger>
        </TabsList>

        <TabsContent value="overview">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
            <Card className="backdrop-blur-sm bg-card/50 border-black/5 shadow-sm hover:shadow-md transition-all duration-200">
              <div className="p-6">
                <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                  <div className="p-2 rounded-full bg-primary/10">
                    <Building2 className="h-5 w-5 text-primary" />
                  </div>
                  Source Information
                </h3>
                <div className="space-y-4">
                  <div>
                    <p className="text-sm text-muted-foreground">Organization</p>
                    <div className="flex items-center gap-2 mt-1">
                      <Building2 className="h-4 w-4 text-muted-foreground" />
                      <span className="font-medium">{source.sourceOrg}</span>
                    </div>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Ownership</p>
                    <span className="capitalize font-medium">{source.ownership}</span>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Visibility</p>
                    <div className="flex items-center gap-2">
                      <div className="p-1 rounded-full bg-secondary/50">
                        {source.visibility === "private" ? <Lock className="h-4 w-4" /> : <Globe className="h-4 w-4" />}
                      </div>
                      <span className="capitalize font-medium">{source.visibility}</span>
                    </div>
                  </div>
                </div>
              </div>
            </Card>

            <Card className="backdrop-blur-sm bg-card/50 border-black/5 shadow-sm hover:shadow-md transition-all duration-200">
              <div className="p-6">
                <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                  <div className="p-2 rounded-full bg-primary/10">
                    <RefreshCw className="h-5 w-5 text-primary" />
                  </div>
                  Sync Status
                </h3>
                <div className="space-y-4">
                  <div>
                    <p className="text-sm text-muted-foreground">Last Sync</p>
                    <span className="font-medium">{source.lastSync}</span>
                  </div>
                  <div>
                    <p className="text-sm text-muted-foreground">Data Points</p>
                    <span className="font-medium">{source.dataPoints}</span>
                  </div>
                </div>
              </div>
            </Card>

            <Card className="backdrop-blur-sm bg-card/50 border-black/5 shadow-sm hover:shadow-md transition-all duration-200">
              <div className="p-6">
                <h3 className="text-lg font-semibold mb-4 flex items-center gap-2">
                  <div className="p-2 rounded-full bg-primary/10">
                    <Database className="h-5 w-5 text-primary" />
                  </div>
                  Available Resources
                </h3>
                <div className="flex flex-wrap gap-2">
                  {source.resourceTypes && source.resourceTypes.length > 0 ? (
                    source.resourceTypes.map((type) => (
                      <Badge 
                        key={type} 
                        variant="secondary" 
                        className="rounded-full px-3 py-1 bg-secondary/50 hover:bg-secondary/70 transition-colors cursor-default"
                      >
                        {type}
                      </Badge>
                    ))
                  ) : (
                    <p className="text-muted-foreground">No resources available</p>
                  )}
                </div>
              </div>
            </Card>
          </div>
        </TabsContent>

        <TabsContent value="permissions">
          <Card className="backdrop-blur-sm bg-card/50 border-black/5">
            <div className="p-6 border-b border-black/5">
              <div className="flex justify-between items-center">
                <div>
                  <h3 className="text-lg font-semibold">Access Control</h3>
                  <p className="text-sm text-muted-foreground">Manage who has access to this source</p>
                </div>
                <Button className="flex items-center gap-2 rounded-full">
                  <Plus className="h-4 w-4" />
                  Add Permission
                </Button>
              </div>
            </div>
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
          </Card>
        </TabsContent>

        <TabsContent value="resources">
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">Resource Management</h3>
            <p className="text-muted-foreground">Configure and manage available resources from this source</p>
          </Card>
        </TabsContent>

        <TabsContent value="settings">
          <Card className="p-6">
            <h3 className="text-lg font-semibold mb-4">Source Settings</h3>
            <p className="text-muted-foreground">Configure source settings and preferences</p>
          </Card>
        </TabsContent>
      </Tabs>

      <div className="mt-6 space-x-2">
        <button
          onClick={() => handleStatusUpdate(SourceStatus.ACTIVE)}
          className="px-4 py-2 bg-green-500 text-white rounded"
        >
          Activate
        </button>
        <button
          onClick={() => handleStatusUpdate(SourceStatus.INACTIVE)}
          className="px-4 py-2 bg-yellow-500 text-white rounded"
        >
          Deactivate
        </button>
        <button
          onClick={handleDelete}
          className="px-4 py-2 bg-red-500 text-white rounded"
        >
          Delete
        </button>
      </div>
    </div>
  );
} 