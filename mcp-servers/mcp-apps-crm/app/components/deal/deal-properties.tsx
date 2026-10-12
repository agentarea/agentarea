import { FieldNote } from "@kit/components/notes";
import { PersonName } from "@kit/components/person-avatar";
import { PropertyFooter, PropertyPanel, PropertyRow as Row, PropertyValue } from "@kit/components/properties";
import { Button } from "@kit/ui/button";
import { Input } from "@kit/ui/input";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@kit/ui/select";
import { DEAL_STATUSES } from "@shared/crm";
import type { DealCard } from "@shared/schema";
import { X } from "lucide-react";
import { useState } from "react";
import { LostReasonForm } from "@/components/lost-reason-form";
import { StageIcon } from "@/components/stage-icon";
import { formatDate, formatMoney, formatPercent } from "@/lib/format";
import { STATUS_META } from "@/lib/meta";
import { noteFor, type DealActions, type DealState } from "./types";

export function DealProperties({ card, state, actions }: { card: DealCard; state: DealState; actions: DealActions }) {
  const { deal } = card;
  const [losing, setLosing] = useState(false);
  const open = deal.status === "open";
  const busy = state.busy !== null;
  const stages = card.stages.filter((s) => s.outcome === null);

  return (
    <PropertyPanel>
      <Row label="Status">
        <Select
          value={deal.status}
          disabled={busy}
          onValueChange={(next) => {
            if (next === deal.status) return;
            if (next === "lost") setLosing(true);
            else if (next === "won") actions.onMove({ status: "won" }, "status");
            else actions.onMove({ reopen: true }, "status");
          }}
        >
          <SelectTrigger size="sm" className="w-full" aria-label="Status">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {DEAL_STATUSES.map((status) => (
              <SelectItem key={status} value={status}>
                <StageIcon
                  stage={
                    status === "open"
                      ? { probability: deal.status === "open" ? deal.stage.probability : 0.1, outcome: null }
                      : { probability: 0, outcome: status }
                  }
                />
                {status === "open" ? (open ? "Open" : "Reopen") : STATUS_META[status].label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {losing && open ? (
          <LostReasonForm
            title={deal.title}
            reasons={card.lostReasons}
            busy={state.busy === "status"}
            error={noteFor(state, "status") ?? null}
            onConfirm={(reason) => actions.onMove({ status: "lost", reason }, "status")}
            onCancel={() => setLosing(false)}
          />
        ) : (
          <FieldNote busy={state.busy === "status"} note={noteFor(state, "status")} />
        )}
      </Row>

      <Row label="Stage">
        <Select
          value={open ? deal.stage.id : ""}
          disabled={busy}
          onValueChange={(stageId) => stageId !== deal.stage.id && actions.onMove({ stageId }, "stage")}
        >
          <SelectTrigger size="sm" className="w-full" aria-label="Stage">
            <SelectValue placeholder={open ? "Stage" : `Reopen in…`} />
          </SelectTrigger>
          <SelectContent>
            {stages.map((s) => (
              <SelectItem key={s.id} value={s.id}>
                <StageIcon stage={s} />
                {s.name}
                <span className="text-subtle-foreground tabular text-xs">{formatPercent(s.probability)}</span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {open && (
          <p className={deal.rotting ? "text-danger text-[11px]" : "text-subtle-foreground text-[11px]"}>
            {deal.daysInStage} {deal.daysInStage === 1 ? "day" : "days"} in stage
            {deal.rotting ? ", longer than it allows" : ""}
          </p>
        )}
        <FieldNote busy={state.busy === "stage"} note={noteFor(state, "stage")} />
      </Row>

      <Row label="Value">
        <PropertyValue className="tabular font-medium">
          {formatMoney(deal.value, deal.currency)}
          {deal.currency !== card.baseCurrency && (
            <span className="text-subtle-foreground font-normal">
              {" "}
              ≈ {formatMoney(deal.baseValue, card.baseCurrency)}
            </span>
          )}
        </PropertyValue>
      </Row>

      <Row label="Owner">
        <PropertyValue>
          <PersonName person={deal.owner} />
        </PropertyValue>
      </Row>

      {open ? (
        <Row label="Close by">
          <div className="flex items-center gap-1">
            <Input
              type="date"
              value={deal.expectedCloseDate ?? ""}
              disabled={busy}
              aria-label="Expected close date"
              className="tabular h-8 flex-1 text-[13px]"
              onChange={(event) => {
                const date = event.target.value;
                if (date && !/^\d{4}-\d{2}-\d{2}$/.test(date)) return;
                actions.onUpdate("close", { expected_close_date: date || null });
              }}
            />
            {deal.expectedCloseDate && (
              <Button
                variant="ghost"
                size="icon"
                className="text-muted-foreground size-8"
                aria-label="Clear expected close date"
                disabled={busy}
                onClick={() => actions.onUpdate("close", { expected_close_date: null })}
              >
                <X />
              </Button>
            )}
          </div>
          <FieldNote busy={state.busy === "close"} note={noteFor(state, "close")} />
        </Row>
      ) : (
        <Row label="Closed">
          <PropertyValue className="tabular">{deal.closedAt ? formatDate(deal.closedAt) : "—"}</PropertyValue>
        </Row>
      )}

      {deal.status === "lost" && (
        <Row label="Reason">
          <PropertyValue>{deal.lostReason ?? "—"}</PropertyValue>
        </Row>
      )}

      <Row label="Source">
        <PropertyValue>{deal.source || <span className="text-subtle-foreground">None</span>}</PropertyValue>
      </Row>

      <PropertyFooter>
        <span className="font-mono">{deal.id}</span>
        <span>Created {formatDate(deal.createdAt)}</span>
        <span>Updated {formatDate(deal.updatedAt)}</span>
      </PropertyFooter>
    </PropertyPanel>
  );
}
