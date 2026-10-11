import { FieldNote } from "@kit/components/notes";
import { PersonAvatar } from "@kit/components/person-avatar";
import { DetailLayout, PropertyPanel } from "@kit/components/properties";
import { DetailSkeleton } from "@kit/components/skeletons";
import { Breadcrumb, RefreshButton } from "@kit/components/view-header";
import { Input } from "@kit/ui/input";
import type { DealCard } from "@shared/schema";
import { ChevronRight, Globe, Handshake, Mail, Phone } from "lucide-react";
import { useState, type ReactNode } from "react";
import { StageIcon } from "@/components/stage-icon";
import { formatPercent } from "@/lib/format";
import { DealActivities } from "./deal-activities";
import { DealProperties } from "./deal-properties";
import { noteFor, type DealActions, type DealState } from "./types";
import { cn } from "@kit/lib/utils";

function Title({ card, state, actions }: { card: DealCard; state: DealState; actions: DealActions }) {
  const [draft, setDraft] = useState<string | null>(null);
  const save = () => {
    const title = draft?.trim();
    setDraft(null);
    if (title && title !== card.deal.title) actions.onUpdate("title", { title });
  };
  return (
    <div className="flex flex-col gap-1">
      {draft === null ? (
        <h1
          className="hover:bg-muted/60 -mx-1.5 cursor-text rounded-md px-1.5 py-0.5 text-xl leading-snug font-semibold tracking-tight"
          title="Click to rename"
          onClick={() => setDraft(card.deal.title)}
        >
          {card.deal.title}
        </h1>
      ) : (
        <Input
          autoFocus
          value={draft}
          aria-label="Title"
          className="h-9 text-lg font-semibold"
          onChange={(event) => setDraft(event.target.value)}
          onBlur={save}
          onKeyDown={(event) => {
            if (event.key === "Enter") save();
            if (event.key === "Escape") setDraft(null);
          }}
        />
      )}
      <p className="text-muted-foreground truncate text-sm">
        {card.deal.company?.name ?? "No company"}
        {card.deal.contacts.length > 0 && ` · ${card.deal.contacts.map((c) => c.name).join(", ")}`}
      </p>
      <FieldNote busy={state.busy === "title"} note={noteFor(state, "title")} />
    </div>
  );
}

/** The open stages as steps: where the deal is, where it has been, a click to move it. */
function StageSteps({ card, state, actions }: { card: DealCard; state: DealState; actions: DealActions }) {
  const { deal } = card;
  const stages = card.stages.filter((s) => s.outcome === null);
  const current = deal.status === "open" ? stages.findIndex((s) => s.id === deal.stage.id) : -1;
  const days = (stageId: string) =>
    card.stageHistory.filter((visit) => visit.stageId === stageId).reduce((sum, visit) => sum + visit.days, 0);
  const visited = new Set(card.stageHistory.map((v) => v.stageId));
  return (
    <ol className="flex flex-wrap gap-1" aria-label="Stages">
      {stages.map((stage, index) => (
        <li key={stage.id} className="min-w-0 flex-1 basis-[120px]">
          <button
            type="button"
            disabled={index === current || state.busy !== null}
            aria-current={index === current ? "step" : undefined}
            onClick={() => actions.onMove({ stageId: stage.id }, "stage")}
            title={
              index === current
                ? `In ${stage.name} for ${deal.daysInStage}d`
                : deal.status === "open"
                  ? `Move to ${stage.name}`
                  : `Reopen in ${stage.name}`
            }
            className={cn(
              "flex h-8 w-full min-w-0 cursor-pointer items-center gap-1.5 rounded-md border px-2 text-left text-xs transition-colors disabled:cursor-default",
              index === current
                ? "border-input bg-accent text-foreground font-medium"
                : visited.has(stage.id)
                  ? "text-foreground hover:bg-muted/60"
                  : "text-muted-foreground hover:bg-muted/60 border-dashed",
            )}
          >
            <StageIcon stage={stage} />
            <span className="min-w-0 flex-1 truncate">{stage.name}</span>
            <span className="text-subtle-foreground tabular shrink-0 text-[11px]">
              {visited.has(stage.id) ? `${days(stage.id)}d` : formatPercent(stage.probability)}
            </span>
          </button>
        </li>
      ))}
    </ol>
  );
}

function Fact({ icon, children }: { icon: ReactNode; children: ReactNode }) {
  return (
    <span className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs [&>svg]:size-3 [&>svg]:shrink-0">
      {icon}
      <span className="truncate">{children}</span>
    </span>
  );
}

function CompanyPanel({ card }: { card: DealCard }) {
  const { company, contacts } = card;
  return (
    <PropertyPanel label="Company and contacts">
      <div className="flex flex-col gap-1">
        <h2 className="text-[13px] font-medium">{company?.name ?? "No company"}</h2>
        {company && (
          <>
            <p className="text-muted-foreground text-xs">
              {[company.industry, company.size && `${company.size} people`, company.city].filter(Boolean).join(" · ")}
            </p>
            {company.domain && <Fact icon={<Globe />}>{company.domain}</Fact>}
            <p className="text-subtle-foreground tabular text-[11px]">
              {company.openDeals} open {company.openDeals === 1 ? "deal" : "deals"} · {company.contacts}{" "}
              {company.contacts === 1 ? "contact" : "contacts"}
            </p>
          </>
        )}
      </div>
      <ul className="flex flex-col gap-2.5 border-t pt-3">
        {contacts.length === 0 && <li className="text-subtle-foreground text-xs">Nobody is linked yet.</li>}
        {contacts.map((contact) => (
          <li key={contact.id} className="flex min-w-0 gap-2">
            <PersonAvatar person={{ name: contact.name, kind: "human" }} className="mt-0.5 size-5" />
            <div className="flex min-w-0 flex-col gap-0.5">
              <span className="truncate text-[13px] font-medium">{contact.name}</span>
              {contact.title && <span className="text-muted-foreground truncate text-xs">{contact.title}</span>}
              {contact.email && (
                <a href={`mailto:${contact.email}`} className="hover:text-foreground min-w-0">
                  <Fact icon={<Mail />}>{contact.email}</Fact>
                </a>
              )}
              {contact.phone && <Fact icon={<Phone />}>{contact.phone}</Fact>}
            </div>
          </li>
        ))}
      </ul>
    </PropertyPanel>
  );
}

export function DealView({ card, state, actions }: { card: DealCard; state: DealState; actions: DealActions }) {
  return (
    <div className="flex flex-col gap-4">
      <header className="flex flex-col gap-1">
        <div className="flex items-center gap-2">
          <Breadcrumb>
            <button
              type="button"
              onClick={actions.onOpenPipeline}
              className="hover:text-foreground inline-flex min-w-0 cursor-pointer items-center gap-1.5 truncate"
            >
              <Handshake className="size-3.5 shrink-0" />
              <span className="truncate">Pipeline</span>
            </button>
            <ChevronRight className="size-3 shrink-0" />
            <span className="text-foreground font-mono font-medium">{card.deal.id}</span>
          </Breadcrumb>
          <RefreshButton
            compact
            className="ml-auto"
            busy={state.busy === "refresh"}
            onClick={actions.onRefresh}
            label="Reload from the CRM server"
          />
        </div>
        <FieldNote note={noteFor(state, "link") ?? noteFor(state, "refresh")} />
      </header>

      <Title card={card} state={state} actions={actions} />

      <DetailLayout
        main={
          <>
            <div className="flex flex-col gap-1">
              <StageSteps card={card} state={state} actions={actions} />
            </div>
            <DealActivities card={card} state={state} actions={actions} />
          </>
        }
        aside={
          <div className="flex flex-col gap-3">
            <DealProperties key={card.deal.status} card={card} state={state} actions={actions} />
            <CompanyPanel card={card} />
          </div>
        }
      />
    </div>
  );
}

export function DealSkeleton() {
  return <DetailSkeleton label="Loading deal" />;
}
