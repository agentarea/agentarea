import { getLocale, getTranslations } from "next-intl/server";
import DeleteButton from "@/components/DeleteButton";
import Panel from "@/components/Panel";
import SourceTypeMark from "@/components/SourceTypeMark";
import { CopyableText } from "@/components/ui/copyable-text";
import { Skeleton } from "@/components/ui/skeleton";
import { listStreamSources } from "@/lib/api";
import { requireApiData } from "@/lib/server-resource";
import { sourceTypeBySlug, type SourceType } from "@/lib/sourceTypes";
import { formatDateTime } from "@/utils/dateUtils";
import { deleteStreamSourceAction } from "../actions";

/** Where the stream's events come from: each source's public URL, and delete for the ones no trigger owns. */
export default async function StreamSources({
  streamId,
  types,
}: {
  streamId: string;
  types: SourceType[];
}) {
  const [t, locale, sourcesResult] = await Promise.all([
    getTranslations("EventsPage.sources"),
    getLocale(),
    listStreamSources(streamId),
  ]);
  const sources = requireApiData(sourcesResult, "stream sources");
  const onDelete = deleteStreamSourceAction.bind(null, streamId);

  return (
    <Panel title={t("title")} count={sources.length}>
      {sources.length === 0 ? (
        <div className="py-6 text-center text-sm text-muted-foreground">
          {t("empty")}
        </div>
      ) : (
        <ul className="space-y-2 p-4">
          {sources.map((source) => {
            const type = sourceTypeBySlug(types, source.source_type);
            const name = type?.name ?? source.source_type ?? source.kind;
            return (
              <li
                key={source.id}
                className="card-item flex flex-col gap-3 p-3 sm:flex-row sm:items-center"
              >
                <div className="flex min-w-0 items-center gap-3 sm:w-48 sm:shrink-0">
                  <SourceTypeMark
                    type={type}
                    slug={source.source_type}
                    size={28}
                  />
                  <div className="min-w-0">
                    <p className="truncate text-sm font-medium">{name}</p>
                    {source.kind === "poll" ? (
                      <p className="note truncate">
                        {source.polled_at
                          ? t("polledAt", {
                              time: formatDateTime(source.polled_at, locale),
                            })
                          : t("notPolledYet")}
                      </p>
                    ) : (
                      type?.verification_header && (
                        <p className="note truncate">
                          {t("signedWithHeader", {
                            header: type.verification_header,
                          })}
                        </p>
                      )
                    )}
                  </div>
                </div>
                <div className="min-w-0 flex-1 space-y-1">
                  {source.webhook_url && (
                    <CopyableText text={source.webhook_url} />
                  )}
                  {source.poll_error && (
                    <p
                      role="alert"
                      className="break-words text-xs text-destructive"
                    >
                      {t("pollError", { error: source.poll_error })}
                    </p>
                  )}
                </div>
                {source.kind !== "platform" && (
                  <div className="flex shrink-0 items-center justify-end">
                    <DeleteButton
                      itemId={source.id}
                      itemName={name}
                      onDelete={onDelete}
                      title={t("deleteTitle")}
                      description={t("deleteDescription", { name })}
                      size="xs"
                    />
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Panel>
  );
}

export async function StreamSourcesSkeleton() {
  const t = await getTranslations("EventsPage.sources");
  return (
    <Panel title={t("title")}>
      <div className="p-4">
        <Skeleton className="h-12 w-full" />
      </div>
    </Panel>
  );
}
