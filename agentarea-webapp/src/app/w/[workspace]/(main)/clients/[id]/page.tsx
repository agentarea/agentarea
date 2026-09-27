"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { notFound, useParams } from "next/navigation";
import { Link as LinkIcon, Loader2, Pencil, Terminal } from "lucide-react";
import type { ClientResponse } from "@/api/client";
import { useAttachableResources } from "@/hooks/use-attachable-resources";
import { resolveMcpRef } from "@/lib/mcp/resolveMcpRef";
import {
  AttachmentSection,
  hydrateAttachments,
  type AttachmentItem,
} from "@/components/AttachmentSection";
import ContentBlock from "@/components/ContentBlock";
import DeleteButton from "@/components/DeleteButton";
import EmptyState from "@/components/EmptyState";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import { DetailSkeleton } from "@/components/Skeleton";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CopyableText } from "@/components/ui/copyable-text";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import Divider from "@/components/ui/divider";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import {
  apiErrorMessage,
  formatApiError,
  isApiNotFound,
} from "@/lib/api-errors";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import {
  addMcpInstanceToClientAction,
  addSkillToClientAction,
  deleteClientAction,
  getClientAction,
  removeMcpInstanceFromClientAction,
  removeSkillFromClientAction,
  updateClientAction,
} from "@/lib/server-actions";
import { harnessOf } from "../harnesses";

const McpIcon = ENTITY_ICONS.mcp;
const SkillIcon = ENTITY_ICONS.skill;

export default function ClientDetailPage() {
  const params = useParams();
  const clientId = params.id as string;
  const t = useTranslations("ClientsPage");
  const tCommon = useTranslations("Common");

  const [client, setClient] = useState<ClientResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [missing, setMissing] = useState(false);
  const resources = useAttachableResources();
  const {
    skills: allSkills,
    mcpInstances: allMcp,
    mcpServers,
  } = resources;

  const [showEdit, setShowEdit] = useState(false);
  const [editName, setEditName] = useState("");
  const [editDescription, setEditDescription] = useState("");
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [refreshError, setRefreshError] = useState<string | null>(null);

  // Refetch after an edit: a failure throws so the caller shows it inline.
  const fetchClient = useCallback(async () => {
    const result = await getClientAction(clientId);
    if (result.error || !result.data) {
      throw new Error(apiErrorMessage(result, t("loadOneFailed")));
    }
    setClient(result.data);
  }, [clientId, t]);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await getClientAction(clientId);
      if (isApiNotFound(result)) {
        setMissing(true);
        return;
      }
      if (result.error || !result.data) {
        setLoadError(apiErrorMessage(result, t("loadOneFailed")));
        return;
      }
      setClient(result.data);
    } catch (err) {
      console.error("Failed to load harness", err);
      setLoadError(`${t("loadOneFailed")}: ${formatApiError(err)}`);
    } finally {
      setLoading(false);
    }
  }, [clientId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  if (missing) notFound();
  if (loading) return <DetailSkeleton />;
  if (loadError || !client) {
    return (
      <EmptyState
        title={t("loadOneFailed")}
        description={loadError ?? undefined}
        action={{ label: tCommon("retry"), onClick: () => void load() }}
      />
    );
  }

  const harness = harnessOf(client.kind);
  const HarnessGlyph = harness.icon;

  const instanceIconSrc = (instance: AttachmentItem) => {
    const resolved = resolveMcpRef(instance.id, allMcp, mcpServers);
    return resolved.status === "unresolved" ? undefined : resolved.iconSrc;
  };

  const handleSave = async () => {
    if (!editName.trim()) return;
    setSaving(true);
    setSaveError(null);
    try {
      const result = await updateClientAction(clientId, {
        name: editName.trim(),
        description: editDescription || null,
      });
      if (result.error) {
        setSaveError(apiErrorMessage(result, t("updateFailed")));
        return;
      }
    } catch (err) {
      console.error("Failed to update harness", err);
      setSaveError(`${t("updateFailed")}: ${formatApiError(err)}`);
      return;
    } finally {
      setSaving(false);
    }
    setShowEdit(false);
    await refresh();
  };

  const refresh = async () => {
    setRefreshError(null);
    try {
      await fetchClient();
    } catch (err) {
      console.error("Failed to reload harness", err);
      setRefreshError(formatApiError(err));
    }
  };

  const syncCmd = `agentarea mcp sync --client=${clientId} --target=${
    client.kind === "harness" ? "codex" : client.kind
  }`;

  return (
    <ContentBlock
      header={{
        breadcrumb: [
          { label: t("title"), href: "/clients" },
          { label: client.name },
        ],
        controls: (
          <div className="flex items-center gap-2 py-1">
            <Button
              size="xs"
              variant="outline"
              onClick={() => {
                setEditName(client.name);
                setEditDescription(client.description || "");
                setSaveError(null);
                setShowEdit(true);
              }}
            >
              <Pencil />
              {tCommon("edit")}
            </Button>
            <DeleteButton
              size="xs"
              itemId={clientId}
              itemName={client.name}
              onDelete={deleteClientAction}
              redirectPath="/clients"
              title={t("deleteTitle")}
              description={t("deleteDescription", { name: client.name })}
            />
          </div>
        ),
      }}
    >
      <div className="mx-auto w-full max-w-4xl overflow-auto p-4 sm:p-6">
        {refreshError && (
          <div className="mb-4 flex flex-col gap-2 sm:flex-row sm:items-start">
            <FormError className="flex-1">{refreshError}</FormError>
            <Button
              size="xs"
              variant="outline"
              className="self-start"
              onClick={() => void refresh()}
            >
              {tCommon("retry")}
            </Button>
          </div>
        )}
        <div className="flex items-start gap-3">
          <span className="flex h-10 w-10 shrink-0 items-center justify-center rounded-md border border-border/60 bg-background text-muted-foreground">
            <HarnessGlyph aria-hidden="true" className="h-5 w-5" />
          </span>
          <div className="min-w-0 space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="text-base font-semibold text-foreground">
                {client.name}
              </h2>
              <Badge variant="outline" className="text-xs">
                {harness.label}
              </Badge>
            </div>
            <p className="text-sm text-muted-foreground">
              {client.description ||
                "A governed, scoped tool bundle an external harness connects to over MCP."}
            </p>
          </div>
        </div>

        <div className="mt-4 space-y-3">
          {client.mcp_endpoint_url && (
            <div className="space-y-1.5">
              <FormLabel icon={LinkIcon}>MCP endpoint</FormLabel>
              <CopyableText text={client.mcp_endpoint_url} />
            </div>
          )}
          <div className="space-y-1.5">
            <FormLabel icon={Terminal}>Sync command</FormLabel>
            <CopyableText text={syncCmd} />
          </div>
        </div>

        <Divider />

        <AttachmentSection
          id="client-mcp"
          title="MCP Servers"
          icon={McpIcon}
          note={
            <p>
              Instances exposed through this harness&apos;s endpoint. Tools keep
              the namespace prefix set on the instance.
            </p>
          }
          triggerText="MCP Server"
          sheetTitle="MCP Servers"
          sheetDescription="Add MCP server instances to this harness's bundle"
          availableTitle="Active MCP Server Instances"
          attached={hydrateAttachments(client.mcp_instances, allMcp)}
          available={allMcp}
          emptyLabel="No MCP servers connected. Add one to expose its tools through the endpoint."
          emptyAvailable={
            <p>
              No MCP server instances yet. Create one under Connections first.
            </p>
          }
          onAdd={(item) => addMcpInstanceToClientAction(clientId, item.id)}
          onRemove={(item) =>
            removeMcpInstanceFromClientAction(clientId, item.id)
          }
          onChanged={fetchClient}
          getIconSrc={instanceIconSrc}
        />

        <Divider />

        <AttachmentSection
          id="client-skills"
          title="Skills"
          icon={SkillIcon}
          note={
            <p>
              Skills reachable through the endpoint&apos;s `activate_skill`
              tool.
            </p>
          }
          triggerText="Skill"
          sheetTitle="Skills"
          sheetDescription="Add skills to this harness's bundle"
          availableTitle="Available Skills"
          attached={hydrateAttachments(client.skills, allSkills)}
          available={allSkills}
          emptyLabel="No skills connected. Add skills the harness should be able to activate."
          emptyAvailable={<p>No skills available. Create one under Skills.</p>}
          onAdd={(item) => addSkillToClientAction(clientId, item.id)}
          onRemove={(item) => removeSkillFromClientAction(clientId, item.id)}
          onChanged={fetchClient}
        />
      </div>

      <Dialog open={showEdit} onOpenChange={setShowEdit}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("edit")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            {saveError && <FormError>{saveError}</FormError>}
            <div className="space-y-1.5">
              <FormLabel htmlFor="client-name" required>
                {t("name")}
              </FormLabel>
              <Input
                id="client-name"
                placeholder="my-codex"
                value={editName}
                onChange={(e) => {
                  setEditName(e.target.value);
                  setSaveError(null);
                }}
              />
            </div>
            <div className="space-y-1.5">
              <FormLabel htmlFor="client-description" optional>
                {t("descriptionLabel")}
              </FormLabel>
              <Textarea
                id="client-description"
                placeholder={t("descriptionPlaceholder")}
                value={editDescription}
                onChange={(e) => setEditDescription(e.target.value)}
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowEdit(false)}
            >
              {tCommon("cancel")}
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={!editName.trim() || saving}
            >
              {saving && <Loader2 className="animate-spin" />}
              {tCommon("save")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ContentBlock>
  );
}
