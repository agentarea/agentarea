import { useTranslations } from "next-intl";
import type { StreamResponse } from "@/api/client/types.gen";
import LinkedCard from "@/components/LinkedCard/LinkedCard";
import { TableDateDisplay } from "@/components/Table/TableDateDisplay";
import { EntityAvatar } from "@/components/ui/entity-avatar";
import { deterministicHue } from "@/lib/avatar-hue";
import { EntityIcon } from "@/lib/entity-icons";
import { isPlatformStream } from "@/lib/platformStream";

/** The stream's tile in the house style: graphite, hued by its id. */
export function StreamAvatar({
  stream,
  size,
}: {
  stream: StreamResponse;
  size: number;
}) {
  return (
    <EntityAvatar
      size={size}
      hue={deterministicHue(stream.id)}
      icon={
        <EntityIcon
          kind={isPlatformStream(stream) ? "platformStream" : "stream"}
        />
      }
      aria-hidden
    />
  );
}

/** A stream in the grid: a LinkedCard like a project's, opening its feed. */
export default function StreamCard({ stream }: { stream: StreamResponse }) {
  const t = useTranslations("EventsPage.streams");

  return (
    <LinkedCard
      href={`/events/${stream.id}`}
      title={stream.name}
      bareIcon
      icon={<StreamAvatar stream={stream} size={40} />}
      subtitle={
        stream.description ? (
          <span className="line-clamp-2 basis-full">{stream.description}</span>
        ) : undefined
      }
    >
      <div className="flex items-center gap-3 text-xs text-muted-foreground">
        {isPlatformStream(stream) && <span>{t("platformLabel")}</span>}
        <TableDateDisplay
          dateString={stream.created_at}
          onlyDate
          relative
          relativeDays={5}
        />
      </div>
    </LinkedCard>
  );
}
