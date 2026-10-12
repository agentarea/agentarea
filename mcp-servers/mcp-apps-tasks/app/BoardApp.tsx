import { useApp, useHostStyles } from "@modelcontextprotocol/ext-apps/react";
import { SquareKanban } from "lucide-react";
import type { BoardSnapshot, TaskDetail, TaskRow } from "@shared/schema";
import type { Status } from "@shared/tasks";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { BoardColumns } from "@/components/board/board-columns";
import { ALL_PROJECTS, ANYONE, BoardToolbar, type BoardMode } from "@/components/board/board-toolbar";
import { IssueList } from "@/components/board/issue-list";
import { BoardSkeleton } from "@kit/components/skeletons";
import { ErrorBanner } from "@kit/components/notes";
import { StandaloneNotice } from "@kit/components/standalone-notice";
import { Page } from "@kit/components/view-header";
import { TooltipProvider } from "@kit/ui/tooltip";
import { matchesText, rowOf } from "@/lib/board";
import { STATUS_META } from "@/lib/meta";
import { messageOf, openAppView, structured } from "@kit/lib/mcp";

export function BoardApp() {
  // Opened directly rather than inside an MCP host: there is no bridge and no data.
  if (window.parent === window) return <StandaloneNotice title="Task board" icon={SquareKanban} server="tasks" />;
  return <ConnectedBoard />;
}

function ConnectedBoard() {
  const [snapshot, setSnapshot] = useState<BoardSnapshot | null>(null);
  const [project, setProject] = useState(ALL_PROJECTS);
  const [assignee, setAssignee] = useState(ANYONE);
  const [text, setText] = useState("");
  const [mode, setMode] = useState<BoardMode>("board");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<Record<string, boolean>>({});
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [composing, setComposing] = useState<Status | null>(null);
  const request = useRef(0);

  /** Filters follow what the server resolved, so a handle like "maya" selects her by id. */
  const adopt = (next: BoardSnapshot) => {
    setSnapshot(next);
    setProject(next.project ?? ALL_PROJECTS);
    setAssignee(next.assignee ?? ANYONE);
  };

  const {
    app,
    isConnected,
    error: connectError,
  } = useApp({
    appInfo: { name: "Task board", version: "0.1.0" },
    capabilities: {},
    onAppCreated: (created) => {
      created.addEventListener("toolinput", ({ arguments: input }) => {
        if (typeof input?.project === "string") setProject(input.project.toUpperCase());
        if (typeof input?.assignee === "string") setAssignee(input.assignee);
      });
      // The entry tool's own result: use it if nothing newer has loaded yet.
      created.addEventListener("toolresult", (result) => {
        try {
          const incoming = structured<BoardSnapshot>(result);
          setSnapshot((current) => current ?? incoming);
        } catch (failure) {
          setError(messageOf(failure));
        }
      });
      created.addEventListener("toolcancelled", ({ reason }) => {
        setError(reason ? `The host cancelled the board: ${reason}` : "The host cancelled the board");
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
        const next = structured<BoardSnapshot>(
          await app.callServerTool({
            name: "get_board_snapshot",
            arguments: {
              ...(project === ALL_PROJECTS ? {} : { project }),
              ...(assignee === ANYONE ? {} : { assignee }),
            },
          }),
        );
        if (id !== request.current) return;
        adopt(next);
        setError(null);
      } catch (failure) {
        if (id === request.current) setError(messageOf(failure));
      } finally {
        if (id === request.current) setLoading(false);
      }
    },
    [app, project, assignee],
  );

  useEffect(() => {
    if (isConnected) void load();
  }, [isConnected, load]);

  const tasks = useMemo(() => (snapshot?.tasks ?? []).filter((t) => matchesText(t, text)), [snapshot, text]);
  const labelColors = useMemo(() => new Map((snapshot?.labels ?? []).map((l) => [l.name, l.color])), [snapshot]);

  const note = (id: string, message: string | null) =>
    setNotes((current) => {
      const { [id]: _previous, ...rest } = current;
      return message ? { ...rest, [id]: message } : rest;
    });
  const patch = (id: string, change: (task: TaskRow) => TaskRow) =>
    setSnapshot((current) => current && { ...current, tasks: current.tasks.map((t) => (t.id === id ? change(t) : t)) });

  const move = async (task: TaskRow, status: Status) => {
    if (!app || saving[task.id]) return;
    const previous = task.status;
    patch(task.id, (t) => ({ ...t, status }));
    note(task.id, null);
    setSaving((current) => ({ ...current, [task.id]: true }));
    try {
      const detail = structured<TaskDetail>(
        await app.callServerTool({ name: "update_task", arguments: { key: task.key, status } }),
      );
      patch(task.id, () => rowOf(detail));
    } catch (failure) {
      patch(task.id, (t) => ({ ...t, status: previous }));
      note(task.id, `Couldn't move to ${STATUS_META[status].label}: ${messageOf(failure)}`);
    } finally {
      setSaving(({ [task.id]: _done, ...rest }) => rest);
    }
  };

  const create = async (input: { title: string; project: string; status: Status }): Promise<string | null> => {
    if (!app || !snapshot) return "Not connected to the tasks server";
    try {
      const detail = structured<TaskDetail>(
        await app.callServerTool({
          name: "create_task",
          arguments: {
            ...input,
            ...(snapshot.assignee && snapshot.assignee !== "unassigned" ? { assignee: snapshot.assignee } : {}),
          },
        }),
      );
      setSnapshot((current) => current && { ...current, tasks: [rowOf(detail), ...current.tasks] });
      return null;
    } catch (failure) {
      return messageOf(failure);
    }
  };

  const open = async (task: TaskRow) => {
    if (!app) return;
    note(task.id, await openAppView(app, "show_task", { key: task.key }));
  };

  const failure = connectError?.message ?? error;
  const viewProps = snapshot && {
    snapshot,
    tasks,
    labelColors,
    saving,
    notes,
    composing,
    onCompose: setComposing,
    onOpen: (task: TaskRow) => void open(task),
    onMove: (task: TaskRow, status: Status) => void move(task, status),
    onCreate: create,
  };

  return (
    <TooltipProvider>
      <Page>
        <BoardToolbar
          snapshot={snapshot}
          shown={tasks.length}
          project={project}
          onProjectChange={(next) => {
            setProject(next);
            setComposing(null);
          }}
          assignee={assignee}
          onAssigneeChange={(next) => {
            setAssignee(next);
            setComposing(null);
          }}
          text={text}
          onTextChange={setText}
          mode={mode}
          onModeChange={setMode}
          loading={loading || !isConnected}
          onRefresh={() => void load()}
        />

        <ErrorBanner message={failure} />

        {viewProps ? (
          <div
            className="transition-opacity duration-200 data-[loading=true]:opacity-60"
            data-loading={loading}
            aria-busy={loading}
          >
            {mode === "board" ? <BoardColumns {...viewProps} /> : <IssueList {...viewProps} />}
          </div>
        ) : (
          !failure && <BoardSkeleton />
        )}
      </Page>
    </TooltipProvider>
  );
}
