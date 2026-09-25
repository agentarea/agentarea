import { useApp, useHostStyles } from "@modelcontextprotocol/ext-apps/react";
import type { FunnelStage, Period } from "@shared/outreach";
import type { EnrolledContact, Snapshot } from "@shared/schema";
import { useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { ChartCard } from "@/components/chart-card";
import { DashboardHeader } from "@/components/dashboard-header";
import { FunnelCard } from "@/components/funnel-card";
import { KpiCards } from "@/components/kpi-cards";
import { PeopleTable } from "@/components/people-table";
import { RepliesCard } from "@/components/replies-card";
import { SignalsCard } from "@/components/signals-card";
import { DashboardSkeleton } from "@/components/dashboard-skeleton";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { StandaloneNotice } from "@/components/standalone-notice";
import { messageOf, openAppView, structured } from "@/lib/mcp";

const ALL = "all";

export function App() {
  // Opened directly rather than inside an MCP host: there is no bridge and no data.
  if (window.parent === window) return <StandaloneNotice title="Outreach dashboard" />;
  return <ConnectedDashboard />;
}

function ConnectedDashboard() {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [campaign, setCampaign] = useState(ALL);
  const [days, setDays] = useState<Period>(30);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [stage, setStage] = useState<FunnelStage | null>(null);
  const [toastTop, setToastTop] = useState(16);
  const request = useRef(0);

  const { app, isConnected, error: connectError } = useApp({
    appInfo: { name: "Outreach dashboard", version: "0.1.0" },
    capabilities: {},
    onAppCreated: (created) => {
      created.addEventListener("toolinput", ({ arguments: input }) => {
        if (typeof input?.campaign === "string") setCampaign(input.campaign);
      });
      // The entry tool's own result: use it if nothing newer has loaded yet.
      created.addEventListener("toolresult", (result) => {
        try {
          const incoming = structured<Snapshot>(result);
          setSnapshot((current) => current ?? incoming);
        } catch (failure) {
          setError(messageOf(failure));
        }
      });
      created.addEventListener("toolcancelled", ({ reason }) => {
        setError(reason ? `The host cancelled the dashboard: ${reason}` : "The host cancelled the dashboard");
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
        const next = structured<Snapshot>(
          await app.callServerTool({
            name: "get_outreach_snapshot",
            arguments: { days, ...(campaign === ALL ? {} : { campaign }) },
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
    [app, campaign, days],
  );

  useEffect(() => {
    if (isConnected) void load();
  }, [isConnected, load]);

  /** Toasts appear next to the control that caused them: the frame may be far taller than the screen. */
  const anchorToasts = (anchor: HTMLElement | null) => {
    if (anchor) setToastTop(Math.max(16, anchor.getBoundingClientRect().top - 72));
  };

  const addToSequence = async (contactId: string, campaignId: string, anchor: HTMLElement | null) => {
    if (!app || !snapshot) return;
    anchorToasts(anchor);
    const setStatus = (status: "in_sequence" | "not_contacted") =>
      setSnapshot((current) =>
        current && {
          ...current,
          signals: current.signals.map((s) => (s.contact.id === contactId ? { ...s, status } : s)),
        },
      );
    setStatus("in_sequence");
    try {
      const enrolled = structured<EnrolledContact>(
        await app.callServerTool({ name: "add_to_sequence", arguments: { contactId, campaign: campaignId } }),
      );
      toast.success(`${enrolled.name} added to ${enrolled.campaign.name}`, {
        description: `${enrolled.company} · step 1 of the sequence is scheduled`,
      });
      void load(true);
    } catch (failure) {
      setStatus("not_contacted");
      toast.error("Couldn't add to sequence", { description: messageOf(failure) });
    }
  };

  const markHandled = async (replyId: string, anchor: HTMLElement | null) => {
    if (!app) return;
    anchorToasts(anchor);
    const setHandled = (handled: boolean) =>
      setSnapshot((current) =>
        current && { ...current, replies: current.replies.map((r) => (r.id === replyId ? { ...r, handled } : r)) },
      );
    setHandled(true);
    try {
      structured(await app.callServerTool({ name: "mark_reply_handled", arguments: { replyId } }));
      toast.success("Reply marked as handled");
    } catch (failure) {
      setHandled(false);
      toast.error("Couldn't update the reply", { description: messageOf(failure) });
    }
  };

  const openLead = (contactId: string) => {
    if (app) void openAppView(app, "show_lead_card", { contact_id: contactId });
  };

  const failure = connectError?.message ?? error;

  return (
    <TooltipProvider>
      <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-4 p-4 sm:p-5">
        <DashboardHeader
          snapshot={snapshot}
          campaign={campaign}
          onCampaignChange={(next) => {
            setCampaign(next);
            setStage(null);
          }}
          days={days}
          onDaysChange={(next) => {
            setDays(next);
            setStage(null);
          }}
          loading={loading || !isConnected}
          onRefresh={() => void load()}
        />

        {failure && (
          <div
            role="alert"
            className="border-danger/30 bg-danger-surface text-danger rounded-lg border px-3 py-2 text-xs font-medium"
          >
            {failure}
          </div>
        )}

        {snapshot ? (
          <div
            className="flex flex-col gap-4 transition-opacity duration-200 data-[loading=true]:opacity-60"
            data-loading={loading}
            aria-busy={loading}
          >
            <KpiCards snapshot={snapshot} />
            <div className="grid gap-4 lg:grid-cols-12">
              <FunnelCard className="lg:col-span-5" funnel={snapshot.funnel} selected={stage} onSelect={setStage} />
              <ChartCard className="lg:col-span-7" snapshot={snapshot} />
            </div>
            <div className="grid gap-4 lg:grid-cols-12">
              <SignalsCard className="lg:col-span-7" snapshot={snapshot} onAddToSequence={addToSequence} />
              <RepliesCard
                className="lg:col-span-5"
                snapshot={snapshot}
                onMarkHandled={markHandled}
                onOpenLead={openLead}
              />
            </div>
            <PeopleTable
              snapshot={snapshot}
              stage={stage}
              onClearStage={() => setStage(null)}
              onOpenLead={openLead}
            />
          </div>
        ) : (
          !failure && <DashboardSkeleton />
        )}
      </div>
      <Toaster position="top-right" offset={{ top: toastTop, right: 16 }} richColors={false} closeButton={false} />
    </TooltipProvider>
  );
}
