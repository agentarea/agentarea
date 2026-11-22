"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { ReactFlowProvider } from "@xyflow/react";
import { MoreHorizontal, Plus } from "lucide-react";
import { FeedLiveProvider } from "@/app/w/[workspace]/(main)/events/components/feed/FeedLive";
import ContentBlock from "@/components/ContentBlock";
import EmptyState from "@/components/EmptyState/EmptyState";
import SubheaderToolbar from "@/components/SubheaderToolbar";
import { Button } from "@/components/ui/button";
import { CountSegmentedControl } from "@/components/ui/count-segmented-control";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { useWorkspaceSlug } from "@/hooks/useWorkspaceNavigation";
import {
  activeCanvas,
  addLink,
  addTile,
  appBoard,
  besideFrame,
  createCanvas,
  deleteCanvas,
  parseStore,
  placeTile,
  removeLink,
  removeTile,
  renameCanvas,
  setActive,
  setFrames,
  setLinkLabel,
  setNoteText,
  tileAt,
  type Canvas,
  type CanvasStore,
  type TileFrame,
  type TileInput,
} from "../utils/canvasState";
import { orgMap } from "../utils/orgMap";
import AddTileDialog, { type CanvasTemplate } from "./AddTileDialog";
import CanvasBoard, { type BoardApi } from "./CanvasBoard";
import { CanvasTileContext, type CanvasTileActions } from "./CanvasContext";
import type { CanvasApp, CanvasData } from "./canvasTypes";
import { useCanvasLive } from "./useCanvasLive";

const newId = () => crypto.randomUUID();

function storageKey(slug: string | null) {
  return `canvas-store:v4:${slug ?? "personal"}`;
}

function readStore(key: string): CanvasStore | null {
  try {
    const raw = window.localStorage.getItem(key);
    return raw ? parseStore(JSON.parse(raw)) : null;
  } catch {
    return null;
  }
}

function writeStore(key: string, store: CanvasStore) {
  try {
    window.localStorage.setItem(key, JSON.stringify(store));
  } catch {
    // A blocked storage only costs the layout on the next visit.
  }
}

/**
 * The apps of the latest read, keeping the previous object for an app whose
 * resource did not change: a new object restarts its iframe, and the page is
 * re-read on a beat for the live layer.
 */
function useStableApps(apps: CanvasApp[]): CanvasApp[] {
  const previous = useRef(new Map<string, { json: string; app: CanvasApp }>());
  return useMemo(() => {
    const next = new Map<string, { json: string; app: CanvasApp }>();
    const stable = apps.map((app) => {
      const json = JSON.stringify(app);
      const kept = previous.current.get(app.id);
      const entry = kept && kept.json === json ? kept : { json, app };
      next.set(app.id, entry);
      return entry.app;
    });
    previous.current = next;
    return stable;
  }, [apps]);
}

export default function CanvasWorkspace({ data }: { data: CanvasData }) {
  return (
    <FeedLiveProvider query="">
      <CanvasWorkspaceBody data={data} />
    </FeedLiveProvider>
  );
}

function CanvasWorkspaceBody({ data: raw }: { data: CanvasData }) {
  const t = useTranslations("CanvasPage");
  const apps = useStableApps(raw.apps);
  const data = useMemo(() => ({ ...raw, apps }), [raw, apps]);
  const key = storageKey(useWorkspaceSlug());
  const [store, setStore] = useState<CanvasStore | null>(null);
  const [adding, setAdding] = useState(false);
  const [renaming, setRenaming] = useState<string | null>(null);
  const boardRef = useRef<BoardApi | null>(null);

  const template = useCallback(
    (kind: CanvasTemplate): Pick<Canvas, "tiles" | "links"> => {
      if (kind === "org") {
        return orgMap({
          agents: data.agents,
          triggers: data.triggers,
          tasks: data.tasks,
          newId,
          labels: {
            sourcesHeader: t("orgSourcesHeader"),
            agentsHeader: t("orgAgentsHeader"),
            liveHeader: t("orgLiveHeader"),
            intro: t("orgIntro"),
            introLink: t("orgIntroLink"),
            flow: ({ tasks, triggers }) =>
              tasks > 0
                ? t("flowTasks", { count: tasks })
                : t("flowTriggers", { count: triggers }),
            liveLink: t("orgLiveLink"),
            spendLink: t("orgSpendLink"),
          },
        });
      }
      // Working apps lead: the large tile should never be a broken one, and
      // apps of one connection sit next to each other.
      const ordered = [...data.apps].sort(
        (a, b) =>
          Number(Boolean(b.resource)) - Number(Boolean(a.resource)) ||
          a.connectionTitle.localeCompare(b.connectionTitle)
      );
      return appBoard({
        appIds: ordered.map((app) => app.id),
        newId,
        note: t("appsNote"),
        noteLink: t("appsNoteLink"),
        tableLink: t("appsTableLink"),
      });
    },
    [data, t]
  );

  // localStorage only exists in the browser, so the store is read after
  // hydration; until then the board is not drawn at all.
  useEffect(() => {
    const saved = readStore(key);
    if (saved) {
      setStore(saved);
      return;
    }
    const org: Canvas = {
      id: newId(),
      title: t("orgCanvas"),
      ...template("org"),
    };
    const apps: Canvas = {
      id: newId(),
      title: t("appsCanvas"),
      ...template("apps"),
    };
    const attention: Canvas = {
      id: newId(),
      title: t("attentionCanvas"),
      tiles: [
        tileAt({ kind: "feed", feed: "attention" }, newId(), { x: 0, y: 0 }),
      ],
      links: [],
    };
    const canvases = [
      ...(data.agents.length > 0 ? [org] : []),
      apps,
      attention,
    ];
    setStore({ activeId: canvases[0].id, canvases });
    // Seeding reads the data once; a later change to it must not reseed.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  useEffect(() => {
    if (store) writeStore(key, store);
  }, [key, store]);

  const canvas = store ? activeCanvas(store) : null;
  const canvasId = canvas?.id ?? "";

  const update = useCallback(
    (change: (current: CanvasStore) => CanvasStore) =>
      setStore((current) => (current ? change(current) : current)),
    []
  );

  const live = useCanvasLive({
    canvas,
    tasks: data.tasks,
    triggers: data.triggers,
  });

  const actions = useMemo<CanvasTileActions>(
    () => ({
      apps: new Map(data.apps.map((app) => [app.id, app])),
      agents: new Map(data.agents.map((agent) => [agent.id, agent])),
      connections: new Map(data.connections.map((c) => [c.id, c])),
      triggers: data.triggers,
      tasks: data.tasks,
      tasksById: new Map(data.tasks.map((task) => [task.id, task])),
      live,
      removeTile: (tileId) =>
        update((current) => removeTile(current, canvasId, tileId)),
      setNote: (tileId, text) =>
        update((current) => setNoteText(current, canvasId, tileId, text)),
      setLinkLabel: (linkId, label) =>
        update((current) => setLinkLabel(current, canvasId, linkId, label)),
      removeLink: (linkId) =>
        update((current) => removeLink(current, canvasId, linkId)),
      openTask: (task, from: TileFrame) => {
        const tile = placeTile(
          {
            kind: "task",
            taskId: task.id,
            agentId: task.agentId,
            title: task.title,
          },
          newId(),
          besideFrame(from, "task")
        );
        update((current) => addTile(current, canvasId, tile));
        window.setTimeout(() => boardRef.current?.focus(tile.id), 50);
      },
    }),
    [data, update, canvasId, live]
  );

  const onFrames = useCallback(
    (frames: Record<string, TileFrame>) =>
      update((current) => setFrames(current, canvasId, frames)),
    [update, canvasId]
  );

  const onLink = useCallback(
    (from: string, to: string) =>
      update((current) =>
        addLink(current, canvasId, { id: newId(), from, to, label: "" })
      ),
    [update, canvasId]
  );

  const onAdd = (input: TileInput) => {
    const centre = boardRef.current?.centre() ?? { x: 0, y: 0 };
    update((current) =>
      addTile(current, canvasId, placeTile(input, newId(), centre))
    );
  };

  const onTemplate = (kind: CanvasTemplate) =>
    update((current) =>
      createCanvas(
        current,
        newId(),
        kind === "org" ? t("orgCanvas") : t("appsCanvas"),
        template(kind)
      )
    );

  const renamingCanvas = store?.canvases.find((c) => c.id === renaming);

  return (
    <ContentBlock
      className="p-0 overflow-hidden"
      header={{
        breadcrumb: [{ label: t("title") }],
        controls: (
          <Button size="xs" onClick={() => setAdding(true)} disabled={!store}>
            <Plus />
            {t("add")}
          </Button>
        ),
      }}
      subheader={
        store && canvas ? (
          <SubheaderToolbar
            categories={
              <CountSegmentedControl
                variant="solid"
                value={canvas.id}
                onChange={(id) => update((current) => setActive(current, id))}
                items={store.canvases.map((item) => ({
                  value: item.id,
                  label: item.title,
                  count: item.tiles.length,
                }))}
              />
            }
            controls={
              <>
                <Button
                  size="xs"
                  variant="ghost"
                  onClick={() =>
                    update((current) =>
                      createCanvas(
                        current,
                        newId(),
                        t("untitledCanvas", {
                          n: current.canvases.length + 1,
                        })
                      )
                    )
                  }
                >
                  <Plus />
                  {t("newCanvas")}
                </Button>
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button
                      size="xs"
                      variant="ghost"
                      aria-label={t("canvasActions")}
                    >
                      <MoreHorizontal />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onSelect={() => setRenaming(canvas.id)}>
                      {t("rename")}
                    </DropdownMenuItem>
                    <DropdownMenuItem
                      disabled={store.canvases.length <= 1}
                      onSelect={() =>
                        update((current) => deleteCanvas(current, canvas.id))
                      }
                    >
                      {t("delete")}
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </>
            }
          />
        ) : null
      }
    >
      {store && canvas && (
        <CanvasTileContext.Provider value={actions}>
          <ReactFlowProvider key={canvas.id}>
            <CanvasBoard
              canvas={canvas}
              apiRef={boardRef}
              onFrames={onFrames}
              onLink={onLink}
            >
              {canvas.tiles.length === 0 && (
                <div className="pointer-events-none absolute inset-0 flex items-center justify-center p-6">
                  <div className="pointer-events-auto">
                    <EmptyState
                      title={t("emptyCanvasTitle")}
                      description={t("emptyCanvasDescription")}
                      iconsType="tasks"
                      action={{
                        label: t("add"),
                        onClick: () => setAdding(true),
                      }}
                    />
                  </div>
                </div>
              )}
            </CanvasBoard>
          </ReactFlowProvider>
        </CanvasTileContext.Provider>
      )}

      <AddTileDialog
        open={adding}
        onOpenChange={setAdding}
        data={data}
        onAdd={onAdd}
        onTemplate={onTemplate}
      />

      <Dialog
        open={Boolean(renamingCanvas)}
        onOpenChange={(open) => !open && setRenaming(null)}
      >
        <DialogContent className="sm:max-w-sm">
          <form
            onSubmit={(event) => {
              event.preventDefault();
              const title = String(
                new FormData(event.currentTarget).get("title") ?? ""
              );
              if (renamingCanvas) {
                update((current) =>
                  renameCanvas(current, renamingCanvas.id, title)
                );
              }
              setRenaming(null);
            }}
          >
            <DialogHeader>
              <DialogTitle>{t("renameTitle")}</DialogTitle>
            </DialogHeader>
            <Input
              name="title"
              defaultValue={renamingCanvas?.title}
              aria-label={t("canvasName")}
              className="my-4"
              autoFocus
            />
            <DialogFooter>
              <Button
                type="button"
                variant="ghost"
                onClick={() => setRenaming(null)}
              >
                {t("cancel")}
              </Button>
              <Button type="submit">{t("save")}</Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </ContentBlock>
  );
}
