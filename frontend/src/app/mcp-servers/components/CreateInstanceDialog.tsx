"use client";

import { useState, useEffect } from "react";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Loader2, CheckCircle, XCircle } from "lucide-react";
import { checkMCPServerInstanceConfiguration } from "@/lib/browser-api";
import { createMCPServerInstance } from "../actions";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { MCPInstanceConfigForm } from "@/components/MCPInstanceConfigForm";

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
  const router = useRouter();

  useEffect(() => {
    if (open && mcpServer) {
      setInstanceName(`${mcpServer.name} Instance`);
      setInstanceDescription(`Instance of ${mcpServer.name}`);
      const initialEnvVars: Record<string, string> = {};
      mcpServer.env_schema?.forEach(envVar => {
        initialEnvVars[envVar.name] = envVar.default || "";
      });
      setEnvVars(initialEnvVars);
      setValidationResult(null);
    }
  }, [open, mcpServer]);

  const handleCancel = () => {
    onOpenChange(false);
    setInstanceName("");
    setInstanceDescription("");
    setEnvVars({});
    setValidationResult(null);
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
          <MCPInstanceConfigForm
            server={mcpServer as any}
            instanceName={instanceName}
            instanceDescription={instanceDescription}
            envVars={envVars}
            onChangeName={setInstanceName}
            onChangeDescription={setInstanceDescription}
            onChangeEnvVar={(key, value) => { setEnvVars(prev => ({ ...prev, [key]: value })); if (validationResult) setValidationResult(null); }}
            onValidate={async () => {
              setIsChecking(true);
              try {
                const checkResult = await checkMCPServerInstanceConfiguration({
                  json_spec: { image: mcpServer.docker_image_url, port: 8000, environment: envVars }
                });
                if (checkResult.error) {
                  toast.error('Failed to validate configuration');
                } else {
                  const validationData = checkResult.data as any;
                  setValidationResult(validationData);
                  if (validationData?.valid) toast.success('Configuration is valid!');
                  else toast.warning(`Configuration has ${validationData?.errors?.length || 0} error(s)`);
                }
              } catch (error) {
                console.error('Validation error:', error);
                toast.error('Failed to validate configuration');
              } finally {
                setIsChecking(false);
              }
            }}
            validateDisabled={isChecking || !instanceName.trim()}
            onForceCreate={async () => {
              setIsCreating(true);
              try {
                const instanceResult = await createMCPServerInstance({
                  name: instanceName,
                  description: instanceDescription,
                  server_spec_id: mcpServer.id,
                  json_spec: { image: mcpServer.docker_image_url, port: 8000, environment: envVars }
                });
                if (instanceResult.error) {
                  const msg = typeof instanceResult.error.detail === 'string' 
                    ? instanceResult.error.detail 
                    : 'Failed to create MCP instance';
                  throw new Error(msg);
                }
                toast.success(`Successfully created ${instanceName}`);
                onOpenChange(false);
                router.refresh();
                setInstanceName("");
                setInstanceDescription("");
                setEnvVars({});
                setValidationResult(null);
              } catch (error: any) {
                console.error('Instance creation error:', error);
                toast.error(error?.message || 'Failed to create MCP instance');
              } finally {
                setIsCreating(false);
              }
            }}
            forceCreateDisabled={isCreating || !instanceName.trim()}
            onSubmit={async (e) => {
              e?.preventDefault();
              if (!validationResult) { toast.warning('Please validate the configuration first'); return; }
              if (validationResult && !validationResult.valid) { toast.error('Configuration validation failed. Use "Force Create" to proceed.'); return; }
              setIsCreating(true);
              try {
                const instanceResult = await createMCPServerInstance({
                  name: instanceName,
                  description: instanceDescription,
                  server_spec_id: mcpServer.id,
                  json_spec: { image: mcpServer.docker_image_url, port: 8000, environment: envVars }
                });
                if (instanceResult.error) {
                  const msg = typeof instanceResult.error.detail === 'string' 
                    ? instanceResult.error.detail 
                    : 'Failed to create MCP instance';
                  throw new Error(msg);
                }
                toast.success(`Successfully created ${instanceName}`);
                onOpenChange(false);
                router.refresh();
                setInstanceName("");
                setInstanceDescription("");
                setEnvVars({});
                setValidationResult(null);
              } catch (error: any) {
                console.error('Instance creation error:', error);
                toast.error(error?.message || 'Failed to create MCP instance');
              } finally {
                setIsCreating(false);
              }
            }}
            submitDisabled={isCreating || !instanceName.trim() || (validationResult ? !validationResult.valid : false)}
            submitLabel={isCreating ? 'Creating...' : 'Create Instance'}
            extraActions={(
              <Button variant="outline" onClick={handleCancel} disabled={isCreating} type="button">
                Cancel
              </Button>
            )}
            showContainerSummary
            containerImage={mcpServer.docker_image_url}
            containerPort={8000}
          />
        </div>
      </DialogContent>
    </Dialog>
  );
}