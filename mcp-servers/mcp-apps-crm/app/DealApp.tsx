import { ErrorBanner } from "@kit/components/notes";
import { StandaloneNotice } from "@kit/components/standalone-notice";
import { Page } from "@kit/components/view-header";
import { messageOf, openAppView, structured } from "@kit/lib/mcp";
import { TooltipProvider } from "@kit/ui/tooltip";
import { useApp, useHostStyles } from "@modelcontextprotocol/ext-apps/react";
import type { ActivityRow, DealCard } from "@shared/schema";
import { Handshake } from "lucide-react";
import { useState } from "react";
import { DealSkeleton, DealView } from "@/components/deal/deal-view";
import type { DealActions, DealState, NewActivity, Where } from "@/components/deal/types";
import { moveArguments } from "@/lib/pipeline";

export function DealApp() {
  if (window.parent === window) return <StandaloneNotice title="Deal card" icon={Handshake} server="CRM" />;
  return <ConnectedDeal />;
}

function ConnectedDeal() {
  const [card, setCard] = useState<DealCard | null>(null);
  const [dealId, setDealId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<DealState>({ busy: null, issue: null });

  const { app, error: connectError } = useApp({
    appInfo: { name: "Deal card", version: "0.1.0" },
    capabilities: {},
    onAppCreated: (created) => {
      created.addEventListener("toolinput", ({ arguments: input }) => {
        if (typeof input?.deal_id === "string") setDealId(input.deal_id);
      });
      // The card renders from the host's `show_deal` result.
      created.addEventListener("toolresult", (result) => {
        try {
          setCard(structured<DealCard>(result));
          setError(null);
        } catch (failure) {
          setError(messageOf(failure));
        }
      });
      created.addEventListener("toolcancelled", ({ reason }) => {
        setError(reason ? `The host cancelled the deal card: ${reason}` : "The host cancelled the deal card");
      });
    },
  });
  useHostStyles(app, app?.getHostContext());

  const id = card?.deal.id ?? dealId;

  /** Runs one change, then reloads the card so every section reflects it. Errors stay next to `where`. */
  const act = async (where: Where, run: () => Promise<unknown>): Promise<boolean> => {
    if (!app || !id || state.busy) return false;
    setState({ busy: where, issue: null });
    try {
      await run();
      setCard(structured<DealCard>(await app.callServerTool({ name: "show_deal", arguments: { deal_id: id } })));
      setError(null);
      setState({ busy: null, issue: null });
      return true;
    } catch (failure) {
      setState({ busy: null, issue: { where, text: messageOf(failure) } });
      return false;
    }
  };

  const update = (args: Record<string, unknown>) => async () =>
    structured(await app!.callServerTool({ name: "update_deal", arguments: { deal_id: id!, ...args } }));

  const actions: DealActions = {
    onMove: (target, where) =>
      void act(where, update("reopen" in target ? { status: "open" } : moveArguments(id!, target))),
    onUpdate: (where, args) => void act(where, update(args)),
    onLog: (activity: NewActivity) =>
      act("log", async () =>
        structured(
          await app!.callServerTool({
            name: "log_activity",
            arguments: {
              deal_id: id!,
              type: activity.type,
              subject: activity.subject,
              done: activity.done,
              ...(activity.note ? { note: activity.note } : {}),
              ...(activity.dueAt ? { due_at: activity.dueAt } : {}),
            },
          }),
        ),
      ),
    onToggle: (activity: ActivityRow, done: boolean) =>
      void act(activity.id, async () =>
        structured(
          await app!.callServerTool({ name: "complete_activity", arguments: { activity_id: activity.id, done } }),
        ),
      ),
    onOpenPipeline: () => {
      if (!app) return;
      void openAppView(app, "show_pipeline", {}).then((note) =>
        setState((current) => ({ ...current, issue: note ? { where: "link", text: note } : null })),
      );
    },
    onRefresh: () => void act("refresh", async () => null),
  };

  const failure = connectError?.message ?? error;

  return (
    <TooltipProvider>
      <Page width="detail">
        <ErrorBanner message={failure} />
        {card ? <DealView card={card} state={state} actions={actions} /> : !failure && <DealSkeleton />}
      </Page>
    </TooltipProvider>
  );
}
