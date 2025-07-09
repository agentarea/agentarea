"use client";

import { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Loader2, Info, CheckCircle, XCircle } from "lucide-react";
import { createMCPServerInstance, checkMCPServerInstanceConfiguration } from "@/lib/api";
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
  const [isChecking, setIsChecking] = useState(false);
  const [validationResult, setValidationResult] = useState<{
    valid: boolean;
    errors: string[];
    warnings: string[];
  } | null>(null);
  const [forceCreate, setForceCreate] = useState(false);
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
    // Clear validation when user changes input
    if (validationResult) {
      setValidationResult(null);
      setForceCreate(false);
    }
  };

  const handleCheckConfiguration = async () => {
    if (!mcpServer) return;

    setIsChecking(true);
    
    try {
      const checkResult = await checkMCPServerInstanceConfiguration({
        json_spec: {
          image: mcpServer.docker_image_url,
          port: 8000,
          environment: envVars,
        }
      });

      if (checkResult.error) {
        toast.error('Failed to validate configuration');
        return;
      }

      setValidationResult(checkResult.data);
      
      if (checkResult.data.valid) {
        toast.success('Configuration is valid!');
      } else {
        toast.warning(`Configuration has ${checkResult.data.errors.length} error(s)`);
      }
    } catch (error) {
      console.error('Validation error:', error);
      toast.error('Failed to validate configuration');
    } finally {
      setIsChecking(false);
    }
  };

  const handleCreateInstance = async (force = false) => {
    if (!mcpServer) return;

    // Validate required environment variables
    const missingRequired = mcpServer.env_schema?.filter(envVar => 
      envVar.required && !envVars[envVar.name]?.trim()
    ) || [];

    if (missingRequired.length > 0) {
      toast.error(`Please fill in required environment variables: ${missingRequired.map(e => e.name).join(', ')}`);
      return;
    }

    // Check if validation is required and hasn't been done
    if (!force && !validationResult) {
      toast.warning('Please validate the configuration first');
      return;
    }

    // If validation failed and not forcing, require explicit force
    if (!force && validationResult && !validationResult.valid) {
      toast.error('Configuration validation failed. Use "Force Create" to proceed anyway.');
      return;
    }

    setIsCreating(true);
    
    try {
      const instanceResult = await createMCPServerInstance({
        name: instanceName,
        description: instanceDescription,
        server_spec_id: mcpServer.id,
        json_spec: {
          image: mcpServer.docker_image_url,
          port: 8000,
          environment: envVars,
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
      setValidationResult(null);
      setForceCreate(false);
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
    setValidationResult(null);
    setForceCreate(false);
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

          {/* Configuration Validation */}
          <Separator />
          <div className="space-y-3">
            <div className="flex items-center gap-2">
              <h4 className="text-sm font-medium">Configuration Validation</h4>
              <Button
                variant="outline"
                size="sm"
                onClick={handleCheckConfiguration}
                disabled={isChecking || !instanceName.trim()}
              >
                {isChecking ? (
                  <>
                    <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                    Checking...
                  </>
                ) : (
                  'Check Configuration'
                )}
              </Button>
            </div>
            
            {validationResult && (
              <Alert variant={validationResult.valid ? "default" : "destructive"}>
                <div className="flex items-center gap-2">
                  {validationResult.valid ? (
                    <CheckCircle className="h-4 w-4 text-green-600" />
                  ) : (
                    <XCircle className="h-4 w-4 text-red-600" />
                  )}
                  <AlertDescription>
                    {validationResult.valid ? (
                      "Configuration is valid and ready for deployment!"
                    ) : (
                      <div>
                        <div className="font-medium mb-1">Configuration errors found:</div>
                        <ul className="text-sm list-disc list-inside space-y-1">
                          {validationResult.errors.map((error, index) => (
                            <li key={index}>{error}</li>
                          ))}
                        </ul>
                      </div>
                    )}
                  </AlertDescription>
                </div>
              </Alert>
            )}
          </div>

          {/* Docker Configuration Summary */}
          <Separator />
          <div className="space-y-2">
            <h4 className="text-sm font-medium">Container Configuration</h4>
            <div className="bg-muted/50 rounded-lg p-3 space-y-1">
              <div className="text-xs"><span className="font-medium">Image:</span> {mcpServer.docker_image_url}</div>
              <div className="text-xs"><span className="font-medium">Port:</span> 8000</div>
            </div>
          </div>
        </div>

        <DialogFooter className="gap-2">
          <Button variant="outline" onClick={handleCancel} disabled={isCreating}>
            Cancel
          </Button>
          
          {validationResult && !validationResult.valid && (
            <Button
              variant="destructive"
              onClick={() => handleCreateInstance(true)}
              disabled={isCreating || !instanceName.trim()}
            >
              {isCreating ? (
                <>
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                  Force Creating...
                </>
              ) : (
                'Force Create'
              )}
            </Button>
          )}
          
          <Button 
            onClick={() => handleCreateInstance(false)} 
            disabled={isCreating || !instanceName.trim() || (validationResult && !validationResult.valid)}
          >
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