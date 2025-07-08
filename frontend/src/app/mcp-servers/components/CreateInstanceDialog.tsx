"use client";

import { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Loader2, Info } from "lucide-react";
import { createMCPServerInstance } from "@/lib/api";
import { useRouter } from "next/navigation";
import { toast } from "sonner";

interface MCPServer {
  id: string;
  name: string;
  description: string;
  docker_image_url: string;
  version: string;
  tags: string[];
  status: string;
  is_public: boolean;
  env_schema?: Array<{
    name: string;
    description: string;
    required: boolean;
    default?: string;
  }>;
}

interface CreateInstanceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  mcpServer: MCPServer | null;
}

export function CreateInstanceDialog({ open, onOpenChange, mcpServer }: CreateInstanceDialogProps) {
  const [instanceName, setInstanceName] = useState("");
  const [instanceDescription, setInstanceDescription] = useState("");
  const [envVars, setEnvVars] = useState<Record<string, string>>({});
  const [isCreating, setIsCreating] = useState(false);
  const router = useRouter();

  // Initialize form when dialog opens
  useEffect(() => {
    if (open && mcpServer) {
      setInstanceName(`${mcpServer.name} Instance`);
      setInstanceDescription(`Instance of ${mcpServer.name}`);
      
      // Initialize environment variables with defaults
      const initialEnvVars: Record<string, string> = {};
      mcpServer.env_schema?.forEach(envVar => {
        if (envVar.default) {
          initialEnvVars[envVar.name] = envVar.default;
        } else {
          initialEnvVars[envVar.name] = "";
        }
      });
      setEnvVars(initialEnvVars);
    }
  }, [open, mcpServer]);

  const handleEnvVarChange = (name: string, value: string) => {
    setEnvVars(prev => ({ ...prev, [name]: value }));
  };

  const handleCreateInstance = async () => {
    if (!mcpServer) return;

    // Validate required environment variables
    const missingRequired = mcpServer.env_schema?.filter(envVar => 
      envVar.required && !envVars[envVar.name]?.trim()
    ) || [];

    if (missingRequired.length > 0) {
      toast.error(`Please fill in required environment variables: ${missingRequired.map(e => e.name).join(', ')}`);
      return;
    }

    setIsCreating(true);
    
    try {
      const instanceResult = await createMCPServerInstance({
        name: instanceName,
        description: instanceDescription,
        server_spec_id: mcpServer.id,
        json_spec: {
          type: "docker",
          image: mcpServer.docker_image_url,
          port: 8000,
          environment: envVars,
          resources: {
            memory_limit: "512m",
            cpu_limit: "0.5"
          }
        }
      });

      if (instanceResult.error) {
        throw new Error(instanceResult.error.detail || 'Failed to create MCP instance');
      }

      toast.success(`Successfully created ${instanceName}`);
      onOpenChange(false);
      router.refresh();
      
      // Reset form
      setInstanceName("");
      setInstanceDescription("");
      setEnvVars({});
    } catch (error) {
      console.error('Instance creation error:', error);
      toast.error(error instanceof Error ? error.message : 'Failed to create MCP instance');
    } finally {
      setIsCreating(false);
    }
  };

  const handleCancel = () => {
    onOpenChange(false);
    // Reset form
    setInstanceName("");
    setInstanceDescription("");
    setEnvVars({});
  };

  if (!mcpServer) return null;

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <span>Configure {mcpServer.name} Instance</span>
            <Badge variant="secondary" className="text-xs">
              {mcpServer.tags?.[0] || 'MCP'}
            </Badge>
          </DialogTitle>
          <DialogDescription>
            {mcpServer.description}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          {/* Instance Configuration */}
          <div className="space-y-3">
            <h4 className="text-sm font-medium">Instance Configuration</h4>
            
            <div className="space-y-2">
              <Label htmlFor="instance-name">Name</Label>
              <Input
                id="instance-name"
                placeholder="Enter instance name"
                value={instanceName}
                onChange={(e) => setInstanceName(e.target.value)}
              />
            </div>

            <div className="space-y-2">
              <Label htmlFor="instance-description">Description</Label>
              <Textarea
                id="instance-description"
                placeholder="Enter instance description"
                value={instanceDescription}
                onChange={(e) => setInstanceDescription(e.target.value)}
                rows={2}
              />
            </div>
          </div>

          {/* Environment Variables */}
          {mcpServer.env_schema && mcpServer.env_schema.length > 0 && (
            <>
              <Separator />
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <h4 className="text-sm font-medium">Environment Variables</h4>
                  <Info className="h-4 w-4 text-muted-foreground" />
                </div>
                
                <div className="space-y-3">
                  {mcpServer.env_schema.map((envVar) => (
                    <div key={envVar.name} className="space-y-2">
                      <div className="flex items-center gap-2">
                        <Label htmlFor={`env-${envVar.name}`} className="text-sm font-medium">
                          {envVar.name}
                        </Label>
                        {envVar.required && (
                          <Badge variant="destructive" className="text-xs px-1">
                            Required
                          </Badge>
                        )}
                      </div>
                      <Input
                        id={`env-${envVar.name}`}
                        placeholder={envVar.default || `Enter ${envVar.name}`}
                        value={envVars[envVar.name] || ""}
                        onChange={(e) => handleEnvVarChange(envVar.name, e.target.value)}
                        className={envVar.required && !envVars[envVar.name]?.trim() ? "border-red-300" : ""}
                      />
                      {envVar.description && (
                        <p className="text-xs text-muted-foreground">{envVar.description}</p>
                      )}
                    </div>
                  ))}
                </div>
              </div>
            </>
          )}

          {/* Docker Configuration Summary */}
          <Separator />
          <div className="space-y-2">
            <h4 className="text-sm font-medium">Container Configuration</h4>
            <div className="bg-muted/50 rounded-lg p-3 space-y-1">
              <div className="text-xs"><span className="font-medium">Image:</span> {mcpServer.docker_image_url}</div>
              <div className="text-xs"><span className="font-medium">Memory:</span> 512MB</div>
              <div className="text-xs"><span className="font-medium">CPU:</span> 0.5 cores</div>
            </div>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={handleCancel} disabled={isCreating}>
            Cancel
          </Button>
          <Button onClick={handleCreateInstance} disabled={isCreating || !instanceName.trim()}>
            {isCreating ? (
              <>
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                Creating...
              </>
            ) : (
              'Create Instance'
            )}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
} 