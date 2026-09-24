import { useApp, useHostStyles } from "@modelcontextprotocol/ext-apps/react";
import type { EnrolledContact, LeadCard } from "@shared/schema";
import { useState } from "react";
import { toast } from "sonner";
import { LeadView, LeadSkeleton } from "@/components/lead/lead-view";
import { StandaloneNotice } from "@/components/standalone-notice";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { messageOf, structured } from "@/lib/mcp";

export function LeadApp() {
  if (window.parent === window) return <StandaloneNotice title="Lead card" />;
  return <ConnectedLead />;
}

function ConnectedLead() {
  const [card, setCard] = useState<LeadCard | null>(null);
  const [contactId, setContactId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<"add" | "handle" | "refresh" | null>(null);
  const [toastTop, setToastTop] = useState(16);

  const { app, error: connectError } = useApp({
    appInfo: { name: "Lead card", version: "0.1.0" },
    capabilities: {},
    onAppCreated: (created) => {
      created.addEventListener("toolinput", ({ arguments: input }) => {
        if (typeof input?.contact_id === "string") setContactId(input.contact_id);
      });
      // The card renders from the host's `show_lead_card` result.
      created.addEventListener("toolresult", (result) => {
        try {
          setCard(structured<LeadCard>(result));
          setError(null);
        } catch (failure) {
          setError(messageOf(failure));
        }
      });
      created.addEventListener("toolcancelled", ({ reason }) => {
        setError(reason ? `The host cancelled the lead card: ${reason}` : "The host cancelled the lead card");
      });
    },
  });
  useHostStyles(app, app?.getHostContext());

  const id = card?.contact.id ?? contactId;

  const refetch = async () => {
    if (!app || !id) return;
    setCard(structured<LeadCard>(await app.callServerTool({ name: "show_lead_card", arguments: { contact_id: id } })));
    setError(null);
  };

  /** Runs one action, then reloads the card so every section reflects it. */
  const act = async (kind: "add" | "handle" | "refresh", anchor: HTMLElement | null, run: () => Promise<string | null>) => {
    if (!app || busy) return;
    if (anchor) setToastTop(Math.max(16, anchor.getBoundingClientRect().bottom + 8));
    setBusy(kind);
    try {
      const done = await run();
      await refetch();
      if (done) toast.success(done);
    } catch (failure) {
      toast.error(kind === "refresh" ? "Couldn't refresh the card" : "The action failed", {
        description: messageOf(failure),
      });
    } finally {
      setBusy(null);
    }
  };

  const failure = connectError?.message ?? error;

  return (
    <TooltipProvider>
      <div className="mx-auto flex w-full max-w-[1180px] flex-col gap-4 p-4 sm:p-5">
        {failure && (
          <div
            role="alert"
            className="border-danger/30 bg-danger-surface text-danger rounded-lg border px-3 py-2 text-xs font-medium"
          >
            {failure}
          </div>
        )}
        {card ? (
          <LeadView
            card={card}
            busy={busy}
            onAddToSequence={(anchor) =>
              act("add", anchor, async () => {
                const campaign = card.targetCampaign!;
                const enrolled = structured<EnrolledContact>(
                  await app!.callServerTool({
                    name: "add_to_sequence",
                    arguments: { contactId: card.contact.id, campaign: campaign.id },
                  }),
                );
                return `${enrolled.name} added to ${enrolled.campaign.name}`;
              })
            }
            onMarkHandled={(anchor) =>
              act("handle", anchor, async () => {
                structured(
                  await app!.callServerTool({ name: "mark_reply_handled", arguments: { replyId: card.reply!.id } }),
                );
                return "Reply marked as handled";
              })
            }
            onRefresh={(anchor) => act("refresh", anchor, async () => null)}
          />
        ) : (
          !failure && <LeadSkeleton />
        )}
      </div>
      <Toaster position="top-right" offset={{ top: toastTop, right: 16 }} />
    </TooltipProvider>
  );
}
