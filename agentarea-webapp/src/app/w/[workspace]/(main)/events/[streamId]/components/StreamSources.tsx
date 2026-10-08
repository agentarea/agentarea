import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";
import type { StreamSourceTypeResponse } from "@/api/client/types.gen";
import { TriggerSourceMark } from "@/app/w/[workspace]/(main)/triggers/components/triggerDisplay";
import DeleteButton from "@/components/DeleteButton";
import { CopyableText } from "@/components/ui/copyable-text";
import { Skeleton } from "@/components/ui/skeleton";
import WorkspaceLink from "@/components/WorkspaceLink";
import { listStreamSources } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import { deleteStreamSourceAction } from "../actions";

/** Where the stream's events come from: each source's public URL, and delete for the ones no trigger owns. */
export default async function StreamSources({
  streamId,
  types,
}: {
  streamId: string;
  types: StreamSourceTypeResponse[];
}) {
  const [t, sourcesResult] = await Promise.all([
    getTranslations("EventsPage.sources"),
    listStreamSources(streamId),
  ]);
  const sources = requireApiData(sourcesResult, "stream sources");
  const typeOf = new Map(types.map((type) => [type.webhook_type, type]));
  const onDelete = deleteStreamSourceAction.bind(null, streamId);

  return (
    <SourcesPanel title={t("title")} count={sources.length}>
      {sources.length === 0 ? (
        <div className="py-6 text-center text-sm text-muted-foreground">
          {t("empty")}
        </div>
      ) : (
        <ul className="space-y-2 p-4">
          {sources.map((source) => {
            const type = source.webhook_type
              ? typeOf.get(source.webhook_type)
              : undefined;
            const name = type?.name ?? source.webhook_type ?? source.kind;
            return (
              <li
                key={source.id}
                className="card-item flex flex-col gap-3 p-3 sm:flex-row sm:items-center"
              >
                <div className="flex min-w-0 items-center gap-3 sm:w-48 sm:shrink-0">
                  <TriggerSourceMark entry={type ?? null} size={28} />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{name}</p>
                    {source.signature_scheme && (
                      <p className="note truncate">
                        {t("signedWithHeader", {
                          header: source.signature_scheme.header,
                        })}
                      </p>
                    )}
                  </div>
                </div>
                <div className="min-w-0 flex-1">
                  {source.webhook_url && (
                    <CopyableText text={source.webhook_url} />
                  )}
                </div>
                <div className="flex shrink-0 items-center justify-end">
                  {source.trigger_id ? (
                    <WorkspaceLink
                      href={`/triggers/${source.trigger_id}`}
                      className="note hover:underline"
                    >
                      {t("ownedByTrigger")}
                    </WorkspaceLink>
                  ) : (
                    <DeleteButton
                      itemId={source.id}
                      itemName={name}
                      onDelete={onDelete}
                      title={t("deleteTitle")}
                      description={t("deleteDescription", { name })}
                      size="xs"
                    />
                  )}
                </div>
              </li>
            );
          })}
        </ul>
      )}
    </SourcesPanel>
  );
}

function SourcesPanel({
  title,
  count,
  children,
}: {
  title: string;
  count?: number;
  children: ReactNode;
}) {
  return (
    <section className="mb-4 rounded-md border border-zinc-200 bg-white card-shadow dark:border-zinc-700 dark:bg-zinc-800">
      <header className="flex items-center justify-between border-b border-zinc-200 px-4 py-3 dark:border-zinc-700">
        <h2 className="text-base font-semibold">{title}</h2>
        {count !== undefined && (
          <span className="note tabular-nums">{count}</span>
        )}
      </header>
      {children}
    </section>
  );
}

export async function StreamSourcesSkeleton() {
  const t = await getTranslations("EventsPage.sources");
  return (
    <SourcesPanel title={t("title")}>
      <div className="p-4">
        <Skeleton className="h-12 w-full" />
      </div>
    </SourcesPanel>
  );
}
