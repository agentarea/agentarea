"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ChevronDown } from "lucide-react";
import { Button } from "@/components/ui/button";
import { MenuRow, MenuSeparator } from "@/components/ui/menu-row";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import { useWorkspaceRouter } from "@/hooks/useWorkspaceNavigation";
import { EntityIcon } from "@/lib/entity-icons";

/** The streams themselves, their sources and forwards: one page each, reached from here. */
export default function StreamsMenu({
  streams,
}: {
  streams: { id: string; name: string }[];
}) {
  const t = useTranslations("EventsPage.streamsMenu");
  const router = useWorkspaceRouter();
  const [open, setOpen] = useState(false);
  const go = (href: string) => {
    setOpen(false);
    router.push(href);
  };
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button size="xs" variant="outline" className="shrink-0 gap-1 px-2">
          <EntityIcon kind="stream" />
          {t("button")}
          <ChevronDown />
        </Button>
      </PopoverTrigger>
      <PopoverContent align="end" className="w-64 p-1">
        <div className="max-h-72 overflow-y-auto">
          {streams.length === 0 ? (
            <p className="px-2 py-1.5 text-xs text-muted-foreground">
              {t("empty")}
            </p>
          ) : (
            streams.map((stream) => (
              <MenuRow
                key={stream.id}
                icon={<EntityIcon kind="stream" className="h-3.5 w-3.5" />}
                label={<span className="truncate">{stream.name}</span>}
                onClick={() => go(`/events/${stream.id}`)}
              />
            ))
          )}
        </div>
        <MenuSeparator />
        <MenuRow label={t("all")} onClick={() => go("/events/streams")} />
      </PopoverContent>
    </Popover>
  );
}
