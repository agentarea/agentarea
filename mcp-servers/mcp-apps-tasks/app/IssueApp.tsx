import { useApp, useHostStyles } from "@modelcontextprotocol/ext-apps/react";
import { SquareKanban } from "lucide-react";
import type { TaskDetail } from "@shared/schema";
import { useRef, useState } from "react";
import { IssueSkeleton, IssueView } from "@/components/issue/issue-view";
import type { Field, FieldState, IssueActions } from "@/components/issue/types";
import { ErrorBanner } from "@kit/components/notes";
import { StandaloneNotice } from "@kit/components/standalone-notice";
import { Page } from "@kit/components/view-header";
import { TooltipProvider } from "@kit/ui/tooltip";
import { messageOf, openAppView, structured } from "@kit/lib/mcp";

export function IssueApp() {
  if (window.parent === window) return <StandaloneNotice title="Issue" icon={SquareKanban} server="tasks" />;
  return <ConnectedIssue />;
}

function ConnectedIssue() {
  const [card, setCard] = useState<TaskDetail | null>(null);
  const [key, setKey] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [state, setState] = useState<FieldState>({ busy: {}, notes: {} });
  const latest = useRef<TaskDetail | null>(null);
  latest.current = card;

  const { app, error: connectError } = useApp({
    appInfo: { name: "Issue", version: "0.1.0" },
    capabilities: {},
    onAppCreated: (created) => {
      created.addEventListener("toolinput", ({ arguments: input }) => {
        if (typeof input?.key === "string") setKey(input.key);
      });
      // The card renders from the host's `show_task` result.
      created.addEventListener("toolresult", (result) => {
        try {
          setCard(structured<TaskDetail>(result));
          setError(null);
        } catch (failure) {
          setError(messageOf(failure));
        }
      });
      created.addEventListener("toolcancelled", ({ reason }) => {
        setError(reason ? `The host cancelled the issue: ${reason}` : "The host cancelled the issue");
      });
    },
  });
  useHostStyles(app, app?.getHostContext());

  const mark = (field: Field, busy: boolean, note?: string) =>
    setState((current) => ({
      busy: { ...current.busy, [field]: busy },
      notes: { ...current.notes, [field]: note },
    }));

  const issueKey = card?.key ?? key;

  const refetch = async () => {
    if (!app || !issueKey) return;
    setCard(structured<TaskDetail>(await app.callServerTool({ name: "show_task", arguments: { key: issueKey } })));
  };

  const actions: IssueActions = {
    onUpdate: (field, args, apply) => {
      const previous = latest.current;
      if (!app || !previous) return;
      setCard(apply(previous));
      mark(field, true);
      void (async () => {
        try {
          setCard(
            structured<TaskDetail>(
              await app.callServerTool({ name: "update_task", arguments: { key: previous.key, ...args } }),
            ),
          );
          mark(field, false);
        } catch (failure) {
          setCard(previous);
          mark(field, false, `Not saved: ${messageOf(failure)}`);
          // Other fields may have changed meanwhile; the server has the truth.
          void refetch().catch(() => undefined);
        }
      })();
    },
    onComment: async (body) => {
      if (!app || !issueKey) return false;
      mark("comment", true);
      try {
        structured(await app.callServerTool({ name: "add_comment", arguments: { key: issueKey, body } }));
        await refetch();
        mark("comment", false);
        return true;
      } catch (failure) {
        mark("comment", false, `Not posted: ${messageOf(failure)}`);
        return false;
      }
    },
    onOpenIssue: (target) => {
      if (!app) return;
      void openAppView(app, "show_task", { key: target }).then((note) => mark("link", false, note ?? undefined));
    },
    onOpenBoard: () => {
      if (!app || !card) return;
      void openAppView(app, "show_task_board", { project: card.project }).then((note) =>
        mark("link", false, note ?? undefined),
      );
    },
    onRefresh: () => {
      mark("refresh", true);
      refetch()
        .then(() => mark("refresh", false))
        .catch((failure) => {
          mark("refresh", false);
          mark("link", false, `Couldn't refresh: ${messageOf(failure)}`);
        });
    },
  };

  const failure = connectError?.message ?? error;

  return (
    <TooltipProvider>
      <Page width="detail">
        <ErrorBanner message={failure} />
        {card ? <IssueView card={card} state={state} actions={actions} /> : !failure && <IssueSkeleton />}
      </Page>
    </TooltipProvider>
  );
}
