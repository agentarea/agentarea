"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { Loader2, Plus } from "lucide-react";
import type { ClientResponse } from "@/api/client/types.gen";
import ContentBlock from "@/components/ContentBlock";
import EmptyState from "@/components/EmptyState/EmptyState";
import FormError from "@/components/FormError";
import FormLabel from "@/components/FormLabel/FormLabel";
import GridAndTableViews from "@/components/GridAndTableViews/GridAndTableViews";
import { ViewModeTabs } from "@/components/HeaderTabs";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import { apiErrorMessage, formatApiError } from "@/lib/api-errors";
import { ENTITY_ICONS } from "@/lib/entity-icons";
import { createClientAction, listClientsAction } from "@/lib/server-actions";
import ClientsSkeleton from "./ClientsSkeleton";
import { HARNESS_OPTIONS, HarnessBadge, HarnessIcon } from "./harnesses";

const McpIcon = ENTITY_ICONS.mcp;
const SkillIcon = ENTITY_ICONS.skill;

function NameChips({
  items,
}: {
  items?: { id: string; name: string }[] | null;
}) {
  const list = items ?? [];
  if (!list.length)
    return <span className="text-xs text-muted-foreground">—</span>;
  return (
    <div className="flex flex-wrap items-center gap-1">
      {list.slice(0, 3).map((i) => (
        <Badge
          key={i.id}
          variant="secondary"
          className="max-w-[120px] truncate text-[10px]"
        >
          {i.name}
        </Badge>
      ))}
      {list.length > 3 && (
        <span className="text-[10px] text-muted-foreground">
          +{list.length - 3}
        </span>
      )}
    </div>
  );
}

export default function ClientsPage() {
  const searchParams = useSearchParams();
  const t = useTranslations("ClientsPage");
  const tCommon = useTranslations("Common");
  const viewMode = searchParams.get("tab") === "table" ? "table" : "grid";
  const [clients, setClients] = useState<ClientResponse[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [createError, setCreateError] = useState<string | null>(null);
  const [showCreate, setShowCreate] = useState(false);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [kind, setKind] = useState("harness");
  const [creating, setCreating] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError(null);
    try {
      const result = await listClientsAction();
      if (result.error || !result.data) {
        setLoadError(apiErrorMessage(result, t("loadFailed")));
        return;
      }
      setClients(result.data as ClientResponse[]);
    } catch (err) {
      console.error("Failed to load harnesses", err);
      setLoadError(`${t("loadFailed")}: ${formatApiError(err)}`);
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const handleCreate = async () => {
    if (!name.trim()) return;
    setCreating(true);
    setCreateError(null);
    try {
      const result = await createClientAction({
        name: name.trim(),
        description: description || null,
        kind,
      });
      if (result.error) {
        setCreateError(apiErrorMessage(result, t("createFailed")));
        return;
      }
      setShowCreate(false);
      setName("");
      setDescription("");
      setKind("harness");
      await load();
    } catch (err) {
      console.error("Failed to add harness", err);
      setCreateError(`${t("createFailed")}: ${formatApiError(err)}`);
    } finally {
      setCreating(false);
    }
  };

  const openCreate = () => {
    setCreateError(null);
    setShowCreate(true);
  };

  const columns = [
    {
      header: t("columnHarness"),
      accessor: "name",
      render: (name: string, client: ClientResponse) => (
        <div className="flex items-center gap-2">
          <HarnessIcon
            kind={client.kind}
            className="h-5 w-5 shrink-0 text-primary"
          />
          <div>
            <div className="font-medium">{name}</div>
            {client.description && (
              <div className="mt-1 max-w-md text-xs text-muted-foreground line-clamp-1">
                {client.description}
              </div>
            )}
          </div>
        </div>
      ),
    },
    {
      header: t("type"),
      accessor: "kind",
      render: (value: string) => <HarnessBadge kind={value} />,
    },
    {
      header: "MCP",
      accessor: "mcp_instances",
      render: (value: ClientResponse["mcp_instances"]) => (
        <NameChips items={value} />
      ),
    },
    {
      header: t("columnSkills"),
      accessor: "skills",
      render: (value: ClientResponse["skills"]) => <NameChips items={value} />,
    },
  ];

  return (
    <ContentBlock
      header={{
        breadcrumb: [{ label: t("title") }],
        description: t("description"),
        controls: (
          <Button className="shrink-0" size="xs" onClick={openCreate}>
            <Plus />
            {t("add")}
          </Button>
        ),
      }}
      subheader={
        <SubheaderToolbar controls={<ViewModeTabs currentTab={viewMode} />} />
      }
    >
      <div>
        {loading ? (
          <ClientsSkeleton viewMode={viewMode} />
        ) : loadError ? (
          <EmptyState
            title={t("loadFailed")}
            description={loadError}
            action={{ label: tCommon("retry"), onClick: () => void load() }}
          />
        ) : (
          <GridAndTableViews
            viewMode={viewMode}
            data={clients}
            columns={columns}
            itemLink={(client: ClientResponse) => `/clients/${client.id}`}
            emptyState={
              <EmptyState
                title={t("emptyTitle")}
                description={t("emptyDescription")}
                hints={[
                  { text: t("emptyHintRegister") },
                  { text: t("emptyHintPick") },
                  { text: t("emptyHintScope") },
                ]}
                iconsType="mcp"
                action={{
                  label: t("add"),
                  onClick: openCreate,
                }}
              />
            }
            cardContent={(client: ClientResponse) => {
              const mcpCount = client.mcp_instances?.length ?? 0;
              const skillCount = client.skills?.length ?? 0;
              return (
                <div className="flex h-full flex-col gap-2">
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex min-w-0 items-center gap-2">
                      <HarnessIcon
                        kind={client.kind}
                        className="h-5 w-5 shrink-0 text-muted-foreground"
                      />
                      <h3 className="truncate text-[15px] font-medium leading-tight tracking-tight">
                        {client.name}
                      </h3>
                    </div>
                    <HarnessBadge kind={client.kind} />
                  </div>
                  {client.description && (
                    <p className="line-clamp-2 text-sm text-muted-foreground">
                      {client.description}
                    </p>
                  )}
                  {/* Counts say what they count. A bare "0 / 2" beside two
                      glyphs asked the reader to decode the icons first. */}
                  <div className="mt-auto flex flex-wrap items-center gap-x-3 gap-y-1 pt-2 text-xs text-muted-foreground">
                    <span className="flex items-center gap-1.5">
                      <McpIcon className="h-3.5 w-3.5" />
                      {t("connectionsCount", { count: mcpCount })}
                    </span>
                    <span className="flex items-center gap-1.5">
                      <SkillIcon className="h-3.5 w-3.5" />
                      {t("skillsCount", { count: skillCount })}
                    </span>
                  </div>
                </div>
              );
            }}
          />
        )}
      </div>

      <Dialog open={showCreate} onOpenChange={setShowCreate}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t("add")}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            {createError && <FormError>{createError}</FormError>}
            <div className="space-y-1.5">
              <FormLabel htmlFor="new-client-name" required>
                {t("name")}
              </FormLabel>
              <Input
                id="new-client-name"
                placeholder="my-codex"
                value={name}
                onChange={(e) => {
                  setName(e.target.value);
                  setCreateError(null);
                }}
              />
            </div>
            <div className="space-y-1.5">
              <FormLabel htmlFor="new-client-description" optional>
                {t("descriptionLabel")}
              </FormLabel>
              <Textarea
                id="new-client-description"
                placeholder={t("descriptionPlaceholder")}
                value={description}
                onChange={(e) => setDescription(e.target.value)}
              />
            </div>
            <div className="space-y-1.5">
              <FormLabel htmlFor="new-client-kind">{t("type")}</FormLabel>
              <Select value={kind} onValueChange={setKind}>
                <SelectTrigger id="new-client-kind">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {HARNESS_OPTIONS.map((option) => (
                    <SelectItem key={option.value} value={option.value}>
                      {option.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              size="sm"
              onClick={() => setShowCreate(false)}
            >
              {tCommon("cancel")}
            </Button>
            <Button onClick={handleCreate} disabled={!name.trim() || creating}>
              {creating ? <Loader2 className="mr-2 animate-spin" /> : null}
              {t("add")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </ContentBlock>
  );
}
