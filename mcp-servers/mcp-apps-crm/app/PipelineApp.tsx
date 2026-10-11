import { InlineStatus, ErrorBanner, type Status } from "@kit/components/notes";
import { BoardSkeleton, StatSkeleton } from "@kit/components/skeletons";
import { StandaloneNotice } from "@kit/components/standalone-notice";
import { Page, type LayoutMode } from "@kit/components/view-header";
import { messageOf, openAppView, structured } from "@kit/lib/mcp";
import { TooltipProvider } from "@kit/ui/tooltip";
import { useApp, useHostStyles } from "@modelcontextprotocol/ext-apps/react";
import type { DealRow, DealUpdate, PipelineSnapshot } from "@shared/schema";
import { Handshake } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";
import { PipelineBoard } from "@/components/pipeline/board";
import { DealList } from "@/components/pipeline/deal-list";
import { PipelineStats } from "@/components/pipeline/pipeline-stats";
import { ALL_OWNERS, PipelineToolbar } from "@/components/pipeline/pipeline-toolbar";
import type { NewDeal } from "@/components/pipeline/types";
import { moveArguments, movedDeal, type MoveTarget } from "@/lib/pipeline";

export function PipelineApp() {
  // Opened directly rather than inside an MCP host: there is no bridge and no data.
  if (window.parent === window) return <StandaloneNotice title="Sales pipeline" icon={Handshake} server="CRM" />;
  return <ConnectedPipeline />;
}

function ConnectedPipeline() {
  const [snapshot, setSnapshot] = useState<PipelineSnapshot | null>(null);
  const [ownerId, setOwnerId] = useState(ALL_OWNERS);
  const [view, setView] = useState<LayoutMode>("board");
  const [query, setQuery] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [status, setStatus] = useState<Status>(null);
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [composing, setComposing] = useState<string | null>(null);
  const [losing, setLosing] = useState<DealRow | null>(null);
  const [lossBusy, setLossBusy] = useState(false);
  const [lossError, setLossError] = useState<string | null>(null);
  const request = useRef(0);

  const {
    app,
    isConnected,
    error: connectError,
  } = useApp({
    appInfo: { name: "Sales pipeline", version: "0.1.0" },
    capabilities: {},
    onAppCreated: (created) => {
      created.addEventListener("toolinput", ({ arguments: input }) => {
        if (typeof input?.owner_id === "string") setOwnerId(input.owner_id);
      });
      // The entry tool's own result: use it if nothing newer has loaded yet.
      created.addEventListener("toolresult", (result) => {
        try {
          const incoming = structured<PipelineSnapshot>(result);
          setSnapshot((current) => current ?? incoming);
        } catch (failure) {
          setError(messageOf(failure));
        }
      });
      created.addEventListener("toolcancelled", ({ reason }) => {
        setError(reason ? `The host cancelled the pipeline: ${reason}` : "The host cancelled the pipeline");
      });
    },
  });
  useHostStyles(app, app?.getHostContext());

  const load = useCallback(
    async (quiet = false) => {
      if (!app) return;
      const id = ++request.current;
      if (!quiet) setLoading(true);
      try {
        const next = structured<PipelineSnapshot>(
          await app.callServerTool({
            name: "get_pipeline_snapshot",
            arguments: ownerId === ALL_OWNERS ? {} : { owner_id: ownerId },
          }),
        );
        if (id !== request.current) return;
        setSnapshot(next);
        setError(null);
      } catch (failure) {
        if (id === request.current) setError(messageOf(failure));
      } finally {
        if (id === request.current) setLoading(false);
      }
    },
    [app, ownerId],
  );

  useEffect(() => {
    if (isConnected) void load();
  }, [isConnected, load]);

  const note = (id: string, message: string | null) =>
    setNotes((current) => {
      const { [id]: _previous, ...rest } = current;
      return message ? { ...rest, [id]: message } : rest;
    });
  const replaceDeal = (deal: DealRow) =>
    setSnapshot((current) => current && { ...current, deals: current.deals.map((d) => (d.id === deal.id ? deal : d)) });

  /** Optimistic: the card moves at once and goes back if the server says no. */
  const move = async (deal: DealRow, target: MoveTarget) => {
    if (!app || !snapshot || saving[deal.id]) return;
    const lost = "status" in target && target.status === "lost";
    if (lost) {
      setLossBusy(true);
      setLossError(null);
    }
    replaceDeal(movedDeal(snapshot, deal, target));
    note(deal.id, null);
    setSaving((current) => ({ ...current, [deal.id]: true }));
    setStatus({ kind: "busy", text: `Saving ${deal.title}…` });
    try {
      const result = structured<DealUpdate>(
        await app.callServerTool({ name: "update_deal", arguments: moveArguments(deal.id, target) }),
      );
      replaceDeal(result.deal);
      setStatus({ kind: "ok", text: `${deal.title}: ${result.changes.join("; ") || "no change"}` });
      if (lost) setLosing(null);
      void load(true);
    } catch (failure) {
      replaceDeal(deal);
      if (lost) setLossError(messageOf(failure));
      else note(deal.id, `Couldn't move: ${messageOf(failure)}`);
      setStatus(null);
    } finally {
      if (lost) setLossBusy(false);
      setSaving(({ [deal.id]: _done, ...rest }) => rest);
    }
  };

  const create = async (input: NewDeal): Promise<string | null> => {
    if (!app) return "Not connected to the CRM server";
    try {
      const deal = structured<DealRow>(
        await app.callServerTool({
          name: "create_deal",
          arguments: { title: input.title, value: input.value, stage_id: input.stageId, owner_id: input.ownerId },
        }),
      );
      setSnapshot((current) => current && { ...current, deals: [deal, ...current.deals] });
      setStatus({ kind: "ok", text: `Created ${deal.title}` });
      void load(true);
      return null;
    } catch (failure) {
      return messageOf(failure);
    }
  };

  const openDeal = async (deal: DealRow) => {
    if (!app) return;
    note(deal.id, await openAppView(app, "show_deal", { deal_id: deal.id }));
  };

  const needle = query.trim().toLowerCase();
  const deals = (snapshot?.deals ?? []).filter(
    (d) =>
      !needle ||
      [d.title, d.company?.name, ...d.contacts.map((c) => c.name)].some((field) =>
        field?.toLowerCase().includes(needle),
      ),
  );
  const failure = connectError?.message ?? error;
  const viewProps = snapshot && {
    snapshot,
    deals,
    saving,
    notes,
    composing,
    onCompose: (stageId: string | null) => {
      setComposing(stageId);
      if (stageId) setLosing(null);
    },
    onCreate: create,
    onOpen: (deal: DealRow) => void openDeal(deal),
    onMove: (deal: DealRow, target: MoveTarget) => void move(deal, target),
    losing,
    lossBusy,
    lossError,
    onAskLost: (deal: DealRow) => {
      setLosing(deal);
      setLossError(null);
      setComposing(null);
    },
    onCancelLost: () => setLosing(null),
  };

  return (
    <TooltipProvider>
      <Page>
        <PipelineToolbar
          snapshot={snapshot}
          shown={deals.length}
          ownerId={ownerId}
          onOwnerChange={(next) => {
            setOwnerId(next);
            setLosing(null);
            setComposing(null);
          }}
          query={query}
          onQueryChange={setQuery}
          view={view}
          onViewChange={setView}
          loading={loading || !isConnected}
          onRefresh={() => void load()}
          status={<InlineStatus status={status} className="w-full truncate sm:w-auto" />}
        />

        <ErrorBanner message={failure} />

        {viewProps ? (
          <div
            className="flex flex-col gap-4 transition-opacity duration-200 data-[loading=true]:opacity-60"
            data-loading={loading}
            aria-busy={loading}
          >
            <PipelineStats snapshot={viewProps.snapshot} />
            {view === "board" ? <PipelineBoard {...viewProps} /> : <DealList {...viewProps} />}
          </div>
        ) : (
          !failure && (
            <div className="flex flex-col gap-4">
              <StatSkeleton />
              <BoardSkeleton label="Loading pipeline" />
            </div>
          )
        )}
      </Page>
    </TooltipProvider>
  );
}
